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


# ---------------------------------------------------------------------------
# 各模块初始化函数（被 StartupChecker 调用）
# ---------------------------------------------------------------------------

def _init_db_pool():
    """启用 DB 连接池"""
    from framework.db import enable_db_pool
    return enable_db_pool()


def _init_sentry():
    """初始化 Sentry 错误追踪"""
    import os
    if not os.environ.get("SENTRY_DSN"):
        return "未配置 SENTRY_DSN，跳过"
    from framework.core.sentry_init import init_sentry
    init_sentry()
    return "已初始化"


def _init_redis():
    """检查 Redis 连接"""
    from django.core.cache import cache
    cache.set("_startup_check", "ok", timeout=5)
    val = cache.get("_startup_check")
    if val != "ok":
        raise RuntimeError(f"Redis 读写验证失败: got {val!r}")
    return "连接正常"


def _init_celery():
    """检查 Celery 是否可用"""
    from django.conf import settings
    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        return "未配置 CELERY_BROKER_URL"
    from djangoProjectTest.celery import app as celery_app
    broker = celery_app.conf.broker_url or "未设置"
    return f"broker={broker[:40]}..."


def _init_channels():
    """检查 Channels (WebSocket) 配置"""
    from django.conf import settings
    channel_layers = getattr(settings, "CHANNEL_LAYERS", {})
    if not channel_layers:
        return "未配置 CHANNEL_LAYERS"
    backend = list(channel_layers.keys())
    return f"backends={backend}"


def _init_audit_signals():
    """注册审计信号"""
    from system.core import audit  # noqa: F401  导入即注册
    return "审计信号已注册"


def _init_request_capture():
    """注册请求捕获钩子"""
    from django.core.signals import request_started
    from system.core.audit import set_current_request

    def capture_request(sender, environ, **kwargs):
        from django.http import HttpRequest
        request = HttpRequest()
        request.META = environ
        set_current_request(request)

    request_started.connect(capture_request, dispatch_uid="core_capture_request")
    return "请求捕获钩子已注册"


def _init_cache_warmup():
    """注册首请求缓存预热"""
    from django.core.signals import request_started
    request_started.connect(_ensure_warmup_once, dispatch_uid="core_warmup_once")
    return "缓存预热已挂载（首请求触发）"


# ---------------------------------------------------------------------------
# 首请求缓存预热
# ---------------------------------------------------------------------------

def _ensure_warmup_once(sender, **kwargs):
    """
    首请求时执行一次缓存预热。
    用信号 + 类级标志保证进程内只跑一次。
    """
    if CoreConfig._warmed:
        return
    CoreConfig._warmed = True
    try:
        from framework.cache import cache_manager
        results = cache_manager.warmup_all(verbose=False)
        ok = sum(1 for v in results.values() if v)
        logger.success(
            f"[core.first_request] 缓存预热完成 ({ok}/{len(results)} ok)"
        )
    except Exception as e:
        logger.warning(f"[core.first_request] 缓存预热失败: {e}")


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------

class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "system.core"
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
        from framework.core.startup import print_startup_banner, StartupChecker
        print_startup_banner(worker=os.environ.get("WORKER_TYPE", "django"))

        # 4) 逐模块启动检查
        checker = StartupChecker()

        # --- 基础设施层 ---
        checker.run_safe("DB连接池", _init_db_pool)
        checker.run_safe("Redis", _init_redis)
        checker.run_safe("Sentry", _init_sentry)
        checker.run_safe("Celery", _init_celery)
        checker.run_safe("Channels", _init_channels)

        # --- Django Apps 检查 ---
        checker.check_apps()

        # --- 业务信号 / 钩子 ---
        checker.run_safe("审计信号", _init_audit_signals)
        checker.run_safe("请求捕获钩子", _init_request_capture)
        checker.run_safe("缓存预热挂载", _init_cache_warmup)

        # 5) 汇总
        result = checker.summary()
        if result["fail"] > 0:
            logger.warning(
                f"[core.ready] 启动完成（{result['fail']} 个模块失败，详见上方日志）"
            )
        else:
            logger.success(
                f"[core.ready] 启动完成 — 全部 {result['ok']} 个模块正常"
            )
