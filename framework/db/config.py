"""
DB 连接池配置 Pydantic 模型
============================

从 settings.DATABASES["default"] 的 **顶层字段** "_pool" 读取。
（Django 会把 OPTIONS 整盘 **conn_params 透传给驱动，所以 pool 必须
放在 OPTIONS 之外、且键名加下划线前缀避免被识别为驱动参数。）

示例（DATABASES 中）：

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "saas",
            "USER": "saas",
            "PASSWORD": "secret",
            "HOST": "db",
            "PORT": "5432",
            "_pool": {                 # ⚠️ 必须在 OPTIONS 之外
                "enabled": True,
                "min_size": 2,
                "max_size": 10,
                "timeout": 30,        # 获取连接超时（秒）
                "max_idle": 600,      # 连接最大空闲时间（秒）
                "max_lifetime": 3600, # 连接最大存活时间（秒）
                "pre_ping": True,     # 使用前先 ping 验证
            }
        }
    }
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class DBPoolConfig(BaseModel):
    """
    数据库连接池配置
    ----------------
    enabled:        是否启用（默认 False，向后兼容）
    min_size:       池中保持的最小空闲连接数
    max_size:       池中允许的最大连接数（硬上限）
    timeout:        获取连接的最长等待时间（秒），超时抛 Queue.Full
    max_idle:       连接空闲超过该秒数将被回收（默认 600s）
    max_lifetime:   单个连接最长存活时间（默认 3600s），到期后强制关闭
    pre_ping:       取连接时是否执行一次轻量查询验证可用性（如 SELECT 1）
    pool_class:     强制指定池类名（用于扩展），默认自动选择
    """

    enabled: bool = Field(default=False, description="是否启用连接池")
    min_size: int = Field(default=2, ge=0, le=200, description="最小空闲连接数")
    max_size: int = Field(default=10, ge=1, le=500, description="最大连接数")
    timeout: float = Field(default=30.0, gt=0, description="获取连接超时（秒）")
    max_idle: float = Field(default=600.0, gt=0, description="最大空闲时间（秒）")
    max_lifetime: float = Field(default=3600.0, gt=0, description="最大存活时间（秒）")
    pre_ping: bool = Field(default=True, description="使用前 ping 验证")
    pool_class: Optional[str] = Field(default=None, description="自定义池类路径")

    # 仅在无法初始化真实池时（如 SQLite / 驱动未装）使用的回退选项
    conn_max_age: int = Field(default=600, ge=0, description="Django 原生连接复用时长（秒）")

    model_config = ConfigDict(extra="ignore", frozen=False)

    @classmethod
    def from_db_options(cls, db_conf: dict | None) -> "DBPoolConfig":
        """
        从 DATABASES[alias] 字典中提取 pool 字段。

        兼容两种键名（按优先级）：
          1. ``"_pool"``     —— 顶层私有字段（推荐；Django 不会把它传给驱动）
          2. ``"OPTIONS"`` -> ``"pool"`` —— 兼容旧配置（注意：这种方式会被 Django
                                  透传给驱动，必须在使用前 pop 掉）

        若 db_conf 为 None 或没有 pool 配置，返回默认（enabled=False）。
        """
        if not db_conf:
            return cls()
        # 1) 顶层 _pool
        top = db_conf.get("_pool") or db_conf.get("POOL")
        if top:
            return cls(**top)
        # 2) OPTIONS.pool（旧路径）
        options = db_conf.get("OPTIONS") or {}
        raw = options.get("pool") or {}
        if raw:
            return cls(**raw)
        return cls()

    def is_applicable(self, engine: str) -> bool:
        """
        判断该后端引擎是否支持池

        规则：
          - PostgreSQL: 支持
          - MySQL: 支持
          - SQLite: 不支持（Django 进程内嵌；启用 conn_max_age 复用）
          - 其他（Oracle / MongoDB 等）：不支持
        """
        if not self.enabled:
            return False
        engine = (engine or "").lower()
        return any(tag in engine for tag in ("postgresql", "postgres", "mysql", "mariadb"))
