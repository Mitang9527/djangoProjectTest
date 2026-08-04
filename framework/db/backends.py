"""
DB 连接池 - Django 后端集成层
================================

策略：透明猴补丁（Monkey Patch）
  - 在 Django ORM 创建 connection 时，把原生 connect 替换为 "从池借/还"
  - 对于 SQLite 引擎，仅设置 CONN_MAX_AGE / CONN_HEALTH_CHECKS
  - 池在 connection 关闭时被归还

原理（以 PostgreSQL 为例）：

  Django 原生路径：
    DatabaseWrapper.get_new_connection()
        -> psycopg2.connect()
    DatabaseWrapper.close()
        -> conn.close()

  替换后路径：
    DatabaseWrapper.get_new_connection()
        -> pool.acquire().raw
    DatabaseWrapper.close()
        -> pool.release(pc, broken=is_broken)

这样业务代码完全无感：ORM 调用、QuerySet、事务、savepoint 全部沿用 Django 原生逻辑。

兼容性关键点
------------
Django 的 DatabaseWrapper.get_new_connection(conn_params) 会把
conn_params 整盘 **conn_params 展开传给驱动 connect()。
SQLite 驱动只接受特定参数 (database / timeout / detect_types 等)，
pool、_pool、_db_pool_config 这种字段会直接触发
TypeError: 'pool' is an invalid keyword argument 崩溃。
本模块从 DATABASES 顶层 _pool 读取，并确保在调用 super 之前
把所有 framework.db 私有字段从 conn_params 中剔除。
"""
from __future__ import annotations

import copy
import threading
from typing import Optional

from loguru import logger

from .config import DBPoolConfig
from .manager import pool_manager

_PATCH_LOCK = threading.Lock()
_PATCHED = False
_ORIGINALS: dict = {}

# framework.db 注入的私有字段，必须在调用 super().get_new_connection() 之前 pop
_PRIVATE_KEYS = (
    "_pool", "POOL",
    "_db_pool_config", "_db_pooled_wrapper",
)


def is_patched() -> bool:
    return _PATCHED


def _sanitize_conn_params(conn_params) -> dict:
    """
    清理 conn_params：
      1. 弹出 framework.db 私有字段
      2. 弹出 OPTIONS.pool（如果用户仍在 OPTIONS 里写了 pool）
    """
    if not isinstance(conn_params, dict):
        return conn_params
    params = copy.deepcopy(conn_params)
    for k in _PRIVATE_KEYS:
        params.pop(k, None)
    options = params.get("OPTIONS")
    if isinstance(options, dict):
        options.pop("pool", None)
    return params


# ─────────────────────────────────────────────────────────────
# 后端子类
# ─────────────────────────────────────────────────────────────
def _make_pooled_wrapper(base_wrapper_class, alias: str, engine: str):
    """
    生成一个继承自 base_wrapper 的子类，
    重写 get_new_connection / close 以走池路径。
    """

    class PooledDatabaseWrapper(base_wrapper_class):
        # 在实例上记录从池借到的连接
        _pooled_conn = None
        _pool_broken = False
        _pool_alias = alias

        def get_new_connection(self, conn_params):
            """从池借一条连接"""
            db_pool_cfg_obj: DBPoolConfig = self.settings_dict.get("_db_pool_config")
            if db_pool_cfg_obj is None:
                # 兜底：直接走原方法（先清理 conn_params 防止 pool 键泄漏）
                return super().get_new_connection(_sanitize_conn_params(conn_params))

            try:
                pool = pool_manager.get(alias)
                pc = pool.acquire()
                self._pooled_conn = pc
                self._pool_broken = False
                return pc.raw
            except Exception as e:
                logger.error(f"[DBPool] {alias} 从池借连接失败，降级到原生连接: {e}")
                # 降级到 Django 原生连接（清理 conn_params）
                return super().get_new_connection(_sanitize_conn_params(conn_params))

        def close(self):
            """归还连接到池（仅当通过池借到时）"""
            if getattr(self, "_pooled_conn", None) is not None:
                try:
                    pool = pool_manager.get(alias)
                    pool.release(self._pooled_conn, broken=self._pool_broken)
                except Exception as e:
                    logger.debug(f"[DBPool] {alias} 归还连接异常: {e}")
                finally:
                    self._pooled_conn = None
                    self._pool_broken = False
            else:
                # 原生路径
                super().close()

        # ── 异常时标记连接为 broken，下次归还时丢弃 ─────
        def _handle_db_error(self, *args, **kwargs):
            try:
                self._pool_broken = True
            except Exception:
                pass
            return super()._handle_db_error(*args, **kwargs)

    PooledDatabaseWrapper.__name__ = f"Pooled{base_wrapper_class.__name__}"
    PooledDatabaseWrapper.__qualname__ = PooledDatabaseWrapper.__name__
    return PooledDatabaseWrapper


# ─────────────────────────────────────────────────────────────
# 公开 API
# ─────────────────────────────────────────────────────────────
def patch_all_backends() -> int:
    """
    为所有需要池的 DB alias 替换 DatabaseWrapper。
    必须在 Django 完成 settings.DATABASES 加载后、首次 ORM 调用前调用。
    推荐在 apps.system.core.AppConfig.ready() 中调用。
    """
    global _PATCHED
    with _PATCH_LOCK:
        if _PATCHED:
            return 0

        from django.conf import settings as dj_settings
        databases = getattr(dj_settings, "DATABASES", {}) or {}

        # 先初始化池（创建实际连接池对象）
        initialized = pool_manager.init_pools()
        if initialized == 0:
            logger.info("[DBPool] 没有可池化的数据库，未做后端替换")
            _PATCHED = True
            return 0

        patched = 0
        for alias, db_conf in databases.items():
            engine = db_conf.get("ENGINE", "")
            # ✅ 从整个 db_conf 读，兼容 _pool 顶层和 OPTIONS.pool 两种写法
            pool_cfg = DBPoolConfig.from_db_options(db_conf)

            if not pool_cfg.is_applicable(engine):
                continue

            try:
                _patch_one_backend(alias, engine, pool_cfg)
                patched += 1
            except Exception as e:
                logger.error(f"[DBPool] {alias} 后端替换失败: {e}")

        _PATCHED = True
        logger.success(f"[DBPool] 已为 {patched} 个后端启用连接池")
        return patched


def _patch_one_backend(alias: str, engine: str, pool_cfg: DBPoolConfig):
    """针对单个 alias 替换后端"""
    engine = (engine or "").lower()

    if "postgres" in engine:
        from django.db.backends.postgresql import base as pg_base
        wrapper_cls = pg_base.DatabaseWrapper
        _apply_patch(alias, wrapper_cls, pool_cfg)
        return

    if "mysql" in engine or "mariadb" in engine:
        from django.db.backends.mysql import base as mysql_base
        wrapper_cls = mysql_base.DatabaseWrapper
        _apply_patch(alias, wrapper_cls, pool_cfg)
        return

    # SQLite/其他: 走 CONN_MAX_AGE 长连接
    from django.db.backends.sqlite3 import base as sqlite_base
    wrapper_cls = sqlite_base.DatabaseWrapper
    _apply_sqlite_fallback(alias, wrapper_cls, pool_cfg)


def _apply_patch(alias: str, wrapper_cls, pool_cfg: DBPoolConfig):
    """注入自定义 wrapper 到 django.db.utils.connections"""
    pooled_cls = _make_pooled_wrapper(wrapper_cls, alias, wrapper_cls.__module__ or "")
    _ORIGINALS[alias] = wrapper_cls

    # 在 settings 注入 _db_pool_config 供 wrapper 内部读取
    _inject_settings(alias, pool_cfg)

    # Hook ConnectionHandler，让它在创建指定 alias 连接时使用 pooled_cls
    _patch_handler(alias, pooled_cls, pool_cfg)


def _patch_handler(alias: str, pooled_cls, pool_cfg: DBPoolConfig):
    """Hook ConnectionHandler，使其在创建指定 alias 连接时使用 pooled_cls"""
    from django.db.utils import ConnectionHandler

    if getattr(ConnectionHandler, "_db_pool_patched", False):
        ConnectionHandler._db_pool_alias_map[alias] = (pooled_cls, pool_cfg)
        return

    original_create = ConnectionHandler.create_connection

    def patched_create_connection(self, alias):
        if alias in ConnectionHandler._db_pool_alias_map:
            pooled_cls_, pool_cfg_ = ConnectionHandler._db_pool_alias_map[alias]
            conn = pooled_cls_(self.db_settings[alias], alias=alias)
            conn.settings_dict["_db_pool_config"] = pool_cfg_
            return conn
        return original_create(self, alias)

    ConnectionHandler.create_connection = patched_create_connection
    ConnectionHandler._db_pool_alias_map = {}
    ConnectionHandler._db_pool_patched = True
    ConnectionHandler._db_pool_alias_map[alias] = (pooled_cls, pool_cfg)


def _inject_settings(alias: str, pool_cfg: DBPoolConfig):
    """把 pool_cfg 写进 DATABASES[alias] 字典（私有键，Django 不会传给驱动）"""
    from django.conf import settings as dj_settings
    if alias in dj_settings.DATABASES:
        dj_settings.DATABASES[alias]["_db_pool_config"] = pool_cfg


def _apply_sqlite_fallback(alias: str, wrapper_cls, pool_cfg: DBPoolConfig):
    """
    SQLite 进程内嵌，不需要池；只设置 CONN_MAX_AGE 复用连接
    """
    from django.conf import settings as dj_settings
    if alias in dj_settings.DATABASES:
        dj_settings.DATABASES[alias]["CONN_MAX_AGE"] = pool_cfg.conn_max_age
        dj_settings.DATABASES[alias]["CONN_HEALTH_CHECKS"] = True
        logger.info(
            f"[DBPool] {alias} (SQLite) 走 CONN_MAX_AGE="
            f"{pool_cfg.conn_max_age}s 长连接复用（非池）"
        )
