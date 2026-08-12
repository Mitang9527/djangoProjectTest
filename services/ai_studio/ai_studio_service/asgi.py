import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_studio_service.settings")

# 服务启动横幅: 标识当前启动的是 AI Studio 服务
try:
    from framework.log_utils.service_banner import emit_startup_banner
except Exception:  # framework 未挂载到路径时 (本地子服务) 降级为简单打印
    def emit_startup_banner(key, extra=None):
        print(f"\n=== SERVICE START: {key} ===\n", flush=True)
emit_startup_banner("ai_studio")

# 触发 Django 初始化（必须在导入 consumers/models 之前）
django_asgi_app = get_asgi_application()

from . import routing  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(routing.websocket_urlpatterns),
    }
)
