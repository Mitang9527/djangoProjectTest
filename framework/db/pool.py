"""
数据库连接池抽象基类与具体实现
================================

设计要点：
  1. 池对象线程安全（Queue + Lock）
  2. 连接健康检查（pre_ping / max_idle / max_lifetime）
  3. 指标埋点（命中率 / 等待数 / 活跃数 / 错误数）
  4. 自动重连（连接断开时透明重连）
  5. 显式 close() 用于进程退出时清理

提供：
  - BasePool           抽象基类
  - PostgreSQLPool     基于 psycopg3 的连接池（推荐）
  - PostgreSQLPool2    基于 psycopg2 + DBUtils 的兼容实现
  - MySQLPool          基于 mysql-connector-python 内置池
"""
from __future__ import annotations

import abc
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .config import DBPoolConfig
from .metrics import PoolMetrics, get_metrics


# ─────────────────────────────────────────────────────────────
# 池化连接包装
# ─────────────────────────────────────────────────────────────
@dataclass
class PooledConnection:
    """池中的单条连接 + 借用元数据"""
    raw: Any                       # 真实驱动连接对象
    backend_pid: Optional[int]    # 后端进程 PID（用于健康检查/日志）
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    use_count: int = 0
    broken: bool = False

    def touch(self):
        self.last_used_at = time.time()
        self.use_count += 1


# ─────────────────────────────────────────────────────────────
# 抽象基类
# ─────────────────────────────────────────────────────────────
class BasePool(abc.ABC):
    """
    数据库连接池抽象基类
    -------------------
    子类必须实现：_create_connection() 与 _close_connection()
    可选重写：    _ping(conn) —— 验证连接是否存活
    """

    def __init__(self, name: str, config: DBPoolConfig, connect_kwargs: Dict[str, Any]):
        self.name = name
        self.config = config
        self.connect_kwargs = connect_kwargs
        self._lock = threading.RLock()
        self._pool: "queue.PriorityQueue[Optional[PooledConnection]]" = queue.PriorityQueue(
            maxsize=config.max_size
        )
        self._created = 0      # 已创建连接数（包含借出）
        self._active = 0       # 借出未还的连接数
        self._closed = False
        self._metrics: PoolMetrics = get_metrics(name)

    # ── 必须由子类实现 ─────────────────────────────
    @abc.abstractmethod
    def _create_connection(self) -> Any:
        """创建一条原生数据库连接"""

    @abc.abstractmethod
    def _close_connection(self, raw: Any) -> None:
        """关闭一条原生连接"""

    def _ping(self, conn: Any) -> bool:
        """
        轻量健康检查：执行 SELECT 1
        子类可重写以使用驱动特定的 ping 方法
        """
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            return True
        except Exception as e:
            logger.debug(f"[{self.name}] pre_ping 失败: {e}")
            return False

    def _get_backend_pid(self, conn: Any) -> Optional[int]:
        """获取后端进程 PID（用于日志）"""
        try:
            if hasattr(conn, "info"):
                return conn.info.get("pid")
            return getattr(conn, "server_version", None) and getattr(conn, "_conn_attrs", {}).get("pid")
        except Exception:
            return None

    # ── 公共 API ────────────────────────────────────
    def _ensure_min_size(self):
        """启动时预热到 min_size"""
        with self._lock:
            while self._created < self.config.min_size and not self._closed:
                try:
                    raw = self._create_connection()
                    self._pool.put_nowait(PooledConnection(
                        raw=raw,
                        backend_pid=self._get_backend_pid(raw),
                    ))
                    self._created += 1
                except Exception as e:
                    logger.warning(f"[{self.name}] 预热连接失败: {e}")
                    break

    def acquire(self) -> PooledConnection:
        """
        获取一条连接
        行为：
          1. 池非空 → 取出，检查健康 & TTL，归还时入池或丢弃
          2. 池空 & 未达 max_size → 新建
          3. 池空 & 已达上限 → 阻塞等待
        """
        if self._closed:
            raise RuntimeError(f"[{self.name}] 连接池已关闭")

        waited = False
        deadline = time.monotonic() + self.config.timeout

        while True:
            try:
                pc = self._pool.get_nowait()
            except queue.Empty:
                # 池空：判断能否新建
                with self._lock:
                    if self._created < self.config.max_size:
                        try:
                            raw = self._create_connection()
                            self._created += 1
                            pc = PooledConnection(
                                raw=raw,
                                backend_pid=self._get_backend_pid(raw),
                            )
                            self._metrics.inc_created()
                        except Exception as e:
                            self._metrics.inc_error("create")
                            logger.error(f"[{self.name}] 创建连接失败: {e}")
                            raise
                    else:
                        # 等待归还
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self._metrics.inc_timeout()
                            raise TimeoutError(
                                f"[{self.name}] 获取连接超时（{self.config.timeout}s），"
                                f"当前活跃={self._active}, 上限={self.config.max_size}"
                            )
                        if not waited:
                            waited = True
                            self._metrics.inc_wait()
                        try:
                            pc = self._pool.get(timeout=min(remaining, 1.0))
                        except queue.Empty:
                            continue

            # 拿到一条候选连接，做健康/TTL 检查
            if self._should_discard(pc):
                self._discard(pc)
                continue

            if self.config.pre_ping and not self._ping(pc.raw):
                self._discard(pc)
                continue

            pc.touch()
            self._active += 1
            self._metrics.inc_acquired()
            return pc

    def release(self, pc: PooledConnection, broken: bool = False):
        """
        归还一条连接
        broken=True 表示业务侧发现连接异常，将丢弃而非放回池
        """
        if pc is None:
            return
        self._active = max(0, self._active - 1)

        if self._closed or broken or pc.broken:
            self._discard(pc)
            return

        try:
            self._pool.put_nowait(pc)
        except queue.Full:
            # 池已满，关闭该连接
            self._discard(pc)

    def _should_discard(self, pc: PooledConnection) -> bool:
        """判断是否超过 idle / lifetime 上限"""
        now = time.time()
        if (now - pc.last_used_at) > self.config.max_idle:
            return True
        if (now - pc.created_at) > self.config.max_lifetime:
            return True
        return False

    def _discard(self, pc: PooledConnection):
        """关闭单条连接并减少计数"""
        try:
            self._close_connection(pc.raw)
        except Exception as e:
            logger.debug(f"[{self.name}] 关闭连接异常: {e}")
        with self._lock:
            self._created = max(0, self._created - 1)
        self._metrics.inc_discarded()

    def close(self):
        """关闭池，清理所有连接"""
        with self._lock:
            self._closed = True
            while not self._pool.empty():
                try:
                    pc = self._pool.get_nowait()
                    self._close_connection(pc.raw)
                except Exception:
                    pass
            self._created = 0
        logger.info(f"[{self.name}] 连接池已关闭")

    # ── 上下文管理 ──────────────────────────────────
    @contextmanager
    def connection(self):
        """
        用作 with pool.connection() as conn:
            conn.cursor().execute(...)
        """
        pc = self.acquire()
        try:
            yield pc.raw
        except Exception:
            pc.broken = True
            raise
        finally:
            self.release(pc, broken=pc.broken)

    # ── 监控 ────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """获取池运行指标快照"""
        with self._lock:
            return {
                "name": self.name,
                "min_size": self.config.min_size,
                "max_size": self.config.max_size,
                "created": self._created,
                "active": self._active,
                "idle": max(0, self._created - self._active),
                "queue_size": self._pool.qsize(),
                "closed": self._closed,
                "metrics": self._metrics.snapshot(),
            }


# ─────────────────────────────────────────────────────────────
# PostgreSQL 实现（基于 psycopg3）
# ─────────────────────────────────────────────────────────────
class PostgreSQLPool(BasePool):
    """PostgreSQL 连接池（推荐使用 psycopg3）"""

    def _create_connection(self) -> Any:
        import psycopg
        return psycopg.connect(**self.connect_kwargs)

    def _close_connection(self, raw: Any) -> None:
        try:
            raw.close()
        except Exception:
            pass

    def _ping(self, conn: Any) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception:
            return False

    def _get_backend_pid(self, conn: Any) -> Optional[int]:
        try:
            return conn.info.backend_pid
        except Exception:
            return None


class PostgreSQLPoolPsycopg2(BasePool):
    """兼容 psycopg2-binary 的 PG 池"""

    def _create_connection(self) -> Any:
        import psycopg2
        # autocommit=True 避免长事务；Django 自行管理事务
        kwargs = dict(self.connect_kwargs)
        kwargs.setdefault("autocommit", True)
        return psycopg2.connect(**kwargs)

    def _close_connection(self, raw: Any) -> None:
        try:
            raw.close()
        except Exception:
            pass

    def _ping(self, conn: Any) -> bool:
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            return True
        except Exception:
            return False

    def _get_backend_pid(self, conn: Any) -> Optional[int]:
        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_backend_pid()")
            pid = cur.fetchone()[0]
            cur.close()
            return pid
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────
# MySQL 实现
# ─────────────────────────────────────────────────────────────
class MySQLPool(BasePool):
    """MySQL 连接池（基于 mysql-connector-python 的内置池）"""

    def __init__(self, name: str, config: DBPoolConfig, connect_kwargs: Dict[str, Any]):
        super().__init__(name, config, connect_kwargs)
        # mysql-connector 自带池管理
        from mysql.connector import pooling
        self._inner_pool = pooling.MySQLConnectionPool(
            pool_name=name,
            pool_size=config.max_size,
            pool_reset_session=True,
            **connect_kwargs,
        )

    def _create_connection(self) -> Any:
        # 不再使用，从 inner_pool 获取
        return self._inner_pool.get_connection()

    def _close_connection(self, raw: Any) -> None:
        try:
            # 归还到 inner pool
            from mysql.connector.errors import PoolError
            if raw.is_connected():
                raw.close()  # 配合 pool_reset_session 自动归还
        except PoolError:
            pass
        except Exception:
            pass

    def _ping(self, conn: Any) -> bool:
        try:
            conn.ping(reconnect=False, attempts=1)
            return True
        except Exception:
            return False

    def _get_backend_pid(self, conn: Any) -> Optional[int]:
        try:
            return conn.server_thread
        except Exception:
            return None


class MySQLPoolPyMySQL(BasePool):
    """PyMySQL 后备实现（无内置池，使用 queue 自管理）"""

    def _create_connection(self) -> Any:
        import pymysql
        return pymysql.connect(**self.connect_kwargs)

    def _close_connection(self, raw: Any) -> None:
        try:
            raw.close()
        except Exception:
            pass

    def _ping(self, conn: Any) -> bool:
        try:
            conn.ping(reconnect=True)
            return True
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────
# 工厂
# ─────────────────────────────────────────────────────────────
def create_pool(
    name: str,
    engine: str,
    config: DBPoolConfig,
    connect_kwargs: Dict[str, Any],
) -> BasePool:
    """
    根据 engine 字符串自动选择池实现
    """
    engine = (engine or "").lower()
    if config.pool_class:
        # 用户自定义
        import importlib
        module_path, cls_name = config.pool_class.rsplit(".", 1)
        cls = getattr(importlib.import_module(module_path), cls_name)
        return cls(name, config, connect_kwargs)

    if "postgres" in engine:
        try:
            import psycopg  # noqa
            return PostgreSQLPool(name, config, connect_kwargs)
        except ImportError:
            try:
                import psycopg2  # noqa
                logger.warning(f"[{name}] psycopg3 未安装，降级到 psycopg2")
                return PostgreSQLPoolPsycopg2(name, config, connect_kwargs)
            except ImportError:
                raise ImportError(
                    "PostgreSQL 池需要 psycopg (推荐) 或 psycopg2-binary，请先安装"
                )
    if "mysql" in engine or "mariadb" in engine:
        try:
            import mysql.connector  # noqa
            return MySQLPool(name, config, connect_kwargs)
        except ImportError:
            try:
                import pymysql  # noqa
                logger.warning(f"[{name}] mysql-connector 未安装，降级到 PyMySQL")
                return MySQLPoolPyMySQL(name, config, connect_kwargs)
            except ImportError:
                raise ImportError(
                    "MySQL 池需要 mysql-connector-python 或 PyMySQL"
                )
    raise ValueError(f"[{name}] 不支持的后端引擎: {engine}")
