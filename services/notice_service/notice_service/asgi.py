import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "notice_service.settings")

# 服务启动横幅: 标识当前启动的是通知服务
try:
    from framework.log_utils.service_banner import emit_startup_banner
except Exception:  # framework 未挂载到路径时 (本地子服务) 降级为简单打印
    def emit_startup_banner(key, extra=None):
        print(f"\n=== SERVICE START: {key} ===\n", flush=True)
emit_startup_banner("notice")

application = get_asgi_application()
