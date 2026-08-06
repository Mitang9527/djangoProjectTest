import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_studio_service.settings")

# 触发 Django 初始化（必须在导入 consumers/models 之前）
django_asgi_app = get_asgi_application()

from . import routing  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(routing.websocket_urlpatterns),
    }
)
