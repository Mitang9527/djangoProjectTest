"""
WebSocket 路由配置
"""
from django.urls import path

# 直接在这里导入和定义路由，避免导入问题
from core.consumers import OnlineUsersConsumer, ChatConsumer, NotificationConsumer

websocket_urlpatterns = [
    path('ws/core/chat/<str:room_name>/', ChatConsumer.as_asgi()),
    path('ws/core/notifications/', NotificationConsumer.as_asgi()),
    path('ws/core/online-users/', OnlineUsersConsumer.as_asgi()),
]
