"""
DB 连接池 - 全局池管理器
==========================

职责：
  1. 在 Django 启动时（apps ready 时）扫描 DATABASES，为每个后端创建池
  2. 提供按 alias 获取池实例
  3. 在进程退出 / Django 关闭时统一关闭所有池

使用：
  # settings/apps.py 自动调用 init_pools()
  # 业务侧按需取用：
  from framework.db import pool_manager
  with pool_manager.get("default").connection() as conn:
      ...
"""
from __future__ import annotations

import atexit
import os
import signal
import threading
from typing import Any, Dict, Optional

from django.conf import settings
from loguru import logger

from .config import DBPoolConfig
from .pool import BasePool, create_pool


class PoolManager:
    """全局连接池管理器（单例）"""

    _instance: Optional["PoolManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._pools: Dict[str, BasePool] = {}
                cls._instance._initialized = False
                # 注册进程退出钩子
                atexit.register(cls._instance.close_all)
                try:
                    signal.signal(signal.SIGTERM, lambda *a: cls._instance.close_all())
                except (ValueError, OSError):
                    pass
            return cls._instance

    # ── 初始化 ──────────────────────────────────────
    def init_pools(self) -> int:
        """
        扫描 settings.DATABASES，为每个 alias 创建池。
        返回成功初始化的池数量。
        """
        if self._initialized:
            return len(self._pools)

        databases = getattr(settings, "DATABASES", {}) or {}
        if not databases:
            logger.warning("DATABASES 未配置，跳过连接池初始化")
            return 0

        initialized = 0
        for alias, db_conf in databases.items():
            if not isinstance(db_conf, dict):
                continue
            engine = db_conf.get("ENGINE", "")
            # ✅ 修复：从顶层 _pool 读取，不再依赖 OPTIONS.pool
            pool_cfg = DBPoolConfig.from_db_options(db_conf)

            if not pool_cfg.is_applicable(engine):
                logger.info(
                    f"[DBPool] {alias} ({engine}) 跳过：不支持/未启用"
                )
                continue

            # 构造 connect_kwargs（剔除 Django 内部字段 + 本模块私有字段）
            connect_kwargs = self._build_connect_kwargs(engine, db_conf)
            try:
                pool = create_pool(alias, engine, pool_cfg, connect_kwargs)
                pool._ensure_min_size()
                self._pools[alias] = pool
                initialized += 1
                logger.success(
                    f"[DBPool] {alias} 初始化完成 engine={engine} "
                    f"min={pool_cfg.min_size} max={pool_cfg.max_size}"
                )
            except Exception as e:
                logger.error(f"[DBPool] {alias} 初始化失败: {e}")

        self._initialized = True
        return initialized

    @staticmethod
    def _build_connect_kwargs(engine: str, db_conf: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 Django DATABASES 配置构造驱动连接参数
        过滤掉 Django 特有字段（ENGINE / NAME / OPTIONS / TEST 等）
        以及 framework.db 注入的私有字段（_pool / _db_pool_config 等）
        """
        skip = {
            "ENGINE", "TEST", "OPTIONS", "CONN_MAX_AGE",
            "CONN_HEALTH_CHECKS", "ATOMIC_REQUESTS", "AUTOCOMMIT",
            # framework.db 私有字段，绝对不能透传给驱动
            "_pool", "POOL",
            "_db_pool_config", "_db_pooled_wrapper",
        }
        kwargs = {k: v for k, v in db_conf.items() if k not in skip and v not in (None, "")}
        engine = (engine or "").lower()

        if "postgres" in engine:
            # psycopg/psycopg2 通用字段
            if "NAME" in db_conf:
                kwargs["dbname"] = db_conf["NAME"]
            if "USER" in db_conf:
                kwargs["user"] = db_conf["USER"]
            if "PASSWORD" in db_conf:
                kwargs["password"] = db_conf["PASSWORD"]
            if "HOST" in db_conf:
                kwargs["host"] = db_conf["HOST"]
            if "PORT" in db_conf:
                kwargs["port"] = db_conf["PORT"]
            for k in ("NAME", "USER", "PASSWORD", "HOST", "PORT"):
                kwargs.pop(k, None)

        elif "mysql" in engine or "mariadb" in engine:
            # mysql-connector / PyMySQL 字段
            if "NAME" in db_conf:
                kwargs["database"] = db_conf["NAME"]
            if "USER" in db_conf:
                kwargs["user"] = db_conf["USER"]
            if "PASSWORD" in db_conf:
                kwargs["password"] = db_conf["PASSWORD"]
            if "HOST" in db_conf:
                kwargs["host"] = db_conf["HOST"]
            if "PORT" in db_conf:
                kwargs["port"] = db_conf["PORT"]
            for k in ("NAME", "USER", "PASSWORD", "HOST", "PORT"):
                kwargs.pop(k, None)
            # mysql-connector 不支持 autocommit=True 这种关键词（PyMySQL 支持）
            kwargs.setdefault("charset", "utf8mb4")
            kwargs.setdefault("autocommit", True)

        return kwargs

    # ── 取用 ────────────────────────────────────────
    def get(self, alias: str = "default") -> BasePool:
        """获取指定 alias 的池（首次访问时懒加载）"""
        if alias in self._pools:
            return self._pools[alias]
        # 懒加载
        if not self._initialized:
            self.init_pools()
        if alias not in self._pools:
            raise KeyError(f"未找到 DB alias={alias} 的连接池")
        return self._pools[alias]

    def has(self, alias: str) -> bool:
        return alias in self._pools

    def all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有池的运行指标"""
        return {alias: pool.stats() for alias, pool in self._pools.items()}

    # ── 关闭 ────────────────────────────────────────
    def close_all(self):
        """关闭所有池（atexit / SIGTERM 时调用）"""
        with self._lock:
            for alias, pool in self._pools.items():
                try:
                    pool.close()
                except Exception as e:
                    logger.warning(f"[DBPool] 关闭 {alias} 时异常: {e}")
            self._pools.clear()
            self._initialized = False


# 全局单例
pool_manager = PoolManager()
