import os

from django.apps import AppConfig
from loguru import logger


def _is_reloader_child() -> bool:
    """
    兼容 runserver autoreload 双进程：
    返回 True 表示是真实工作子进程。
    """
    import sys
    if "--noreload" in sys.argv:
        return True
    return os.environ.get("RUN_MAIN") == "true"


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "核心应用"

    _initialized = False  # 类级去重：runserver 父子进程都会触发一次
    _warmed = False  # 缓存预热去重

    def ready(self) -> None:
        # 1) 跳过 autoreload 父进程（它只负责监听文件变化并重启子进程）
        if not _is_reloader_child():
            return

        # 2) 类级去重
        if CoreConfig._initialized:
            return
        CoreConfig._initialized = True

        # 3) 启动横幅
        from utils.startup import print_startup_banner, log_init_phase
        print_startup_banner(worker=os.environ.get("WORKER_TYPE", "django"))

        # 4) 启用 DB 连接池（utils.db 模块的入口）
        try:
            from utils.db import enable_db_pool
            patched = log_init_phase("DB连接池", enable_db_pool)
        except Exception as e:
            logger.error(f"DB 连接池启用失败（继续使用 Django 原生连接）: {e}")
            patched = 0

        # 5) 缓存预热延后到首个请求（避免 ready() 内访问 DB 触发 RuntimeWarning）
        #    调度思路：在第一个 request 到达时异步执行一次 warmup
        from django.core.signals import request_started
        request_started.connect(_ensure_warmup_once, dispatch_uid="core_warmup_once")

        # 6) 汇总
        logger.success(
            f"[core.ready] 启动初始化完成 (pool={patched})"
        )


def _ensure_warmup_once(sender, **kwargs):
    """
    首请求时执行一次缓存预热。
    用信号 + 类级标志保证进程内只跑一次。
    """
    if CoreConfig._warmed:
        return
    CoreConfig._warmed = True
    try:
        from utils.cache import cache_manager
        results = cache_manager.warmup_all(verbose=False)
        ok = sum(1 for v in results.values() if v)
        logger.success(
            f"[core.first_request] 缓存预热完成 ({ok}/{len(results)} ok)"
        )
    except Exception as e:
        logger.warning(f"[core.first_request] 缓存预热失败: {e}")
