"""
DB 连接池 Django 集成 - Apps Ready 钩子
=========================================

将连接池挂接到 Django 启动流程：
  1. settings.DATABASES 加载完后，由本 AppConfig.ready() 自动 patch 后端
  2. 进程退出时通过 PoolManager.atexit 钩子统一关闭池

启用方法（任选其一）：
  方式 A（推荐）：在 settings 的 INSTALLED_APPS 中加入本应用
    INSTALLED_APPS = [..., 'framework.db']
    -> framework.db.apps.DBPoolConfig.ready() 自动执行

  方式 B：手动调用（在 wsgi/asgi 启动脚本）
    from framework.db import patch_all_backends
    patch_all_backends()
"""
from __future__ import annotations

import os

from loguru import logger


def _is_reloader_child() -> bool:
    """
    兼容 runserver autoreload 的双进程情况。
    只有真实的工作子进程（RUN_MAIN=true）才执行重资源初始化。
    """
    # 命令行显式指定 --noreload 时只有单进程
    import sys
    if "--noreload" in sys.argv:
        return True
    # runserver 默认会启动一个父进程（reloader）和子进程（worker）
    # RUN_MAIN 在子进程中被设置为 'true'
    return os.environ.get("RUN_MAIN") == "true"


class DBPoolConfig:
    """
    DB 连接池 AppConfig

    注意：这里有意不继承 AppConfig，而是用普通类 + 手动挂载，
    因为 framework.db 不是 Django app，避免引入额外 INSTALLED_APPS 复杂度。
    用户可以在自己的 AppConfig.ready() 中调用 enable_db_pool()。
    """
    name = "framework.db"
    verbose_name = "DB 连接池"
    ready_called = False

    @classmethod
    def ready(cls):
        """Django 自动调用入口（需要在 INSTALLED_APPS 中加入 'framework.db'）"""
        from .backends import patch_all_backends
        # 避免 autoreload 时执行两次
        if cls.ready_called and not _is_reloader_child():
            return
        cls.ready_called = True
        try:
            patch_all_backends()
        except Exception as e:
            logger.error(f"[DBPool] ready() 失败: {e}")
        # 安装慢查询监控（全局计时 + 慢查询指标）
        try:
            from .monitoring import install_slow_query_monitor
            from django.conf import settings
            threshold = getattr(settings, "DB_SLOW_QUERY_THRESHOLD", 1.0)
            install_slow_query_monitor(threshold=threshold)
        except Exception as e:
            logger.error(f"[DBPool] 慢查询监控安装失败: {e}")


def enable_db_pool() -> int:
    """
    手动入口：返回成功 patch 的后端数量

    用法（任选其一）：
        # 1) 在 wsgi.py / asgi.py / manage.py 顶层
        from framework.db import enable_db_pool
        enable_db_pool()

        # 2) 在任意 AppConfig.ready() 中
        from framework.db.apps import enable_db_pool
        enable_db_pool()
    """
    from .backends import patch_all_backends, is_patched
    if is_patched():
        logger.debug("[DBPool] 已经 patch 过，跳过")
        return 0
    return patch_all_backends()


# 默认 app config（Django < 3.2 兼容）
default_app_config = "framework.db.apps.DBPoolConfig"
