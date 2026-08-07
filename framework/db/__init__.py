"""
DB 连接池 - 统一包入口
========================

提供对 Django ORM 的零侵入式数据库连接池增强。

支持的后端：
  - PostgreSQL   (psycopg3 / psycopg2-binary)
  - MySQL        (mysql-connector-python / PyMySQL)
  - SQLite       (内置 CONN_MAX_AGE 长连接复用)

模块组成：
  pool          - 池抽象基类与具体实现（PG/MySQL）
  manager       - 全局池注册与获取
  backends      - 猴补丁 Django DatabaseWrapper，透明注入
  metrics       - 命中率/等待数/活跃数监控
  config        - 池配置 Pydantic 模型
  apps          - DBPoolConfig + enable_db_pool() 入口
"""
from .config import DBPoolConfig
from .manager import pool_manager, PoolManager
from .backends import patch_all_backends, is_patched
from .apps import enable_db_pool, DBPoolConfig as DBPoolAppConfig

__all__ = [
    "DBPoolConfig",
    "DBPoolAppConfig",
    "pool_manager",
    "PoolManager",
    "patch_all_backends",
    "enable_db_pool",
    "is_patched",
]
