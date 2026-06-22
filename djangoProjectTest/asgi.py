"""
ASGI config for djangoProjectTest project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / 'apps'))

# 统一加载环境变量
from utils.env_loader import load_env_file, get_env_type
load_env_file()

# 获取环境类型，决定加载哪个 settings
env_type = get_env_type()
if env_type == "PROD":
    default_settings = "djangoProjectTest.settings.prod"
else:
    default_settings = "djangoProjectTest.settings.dev"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path

# 获取 Django ASGI 应用
django_asgi_app = get_asgi_application()

# 在这里直接导入消费者
from core.consumers import OnlineUsersConsumer, ChatConsumer, NotificationConsumer

websocket_urlpatterns = [
    path('ws/core/chat/<str:room_name>/', ChatConsumer.as_asgi()),
    path('ws/core/notifications/', NotificationConsumer.as_asgi()),
    path('ws/core/online-users/', OnlineUsersConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})
