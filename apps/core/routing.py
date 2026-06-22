"""
Core 应用的 WebSocket 路由
"""
from django.urls import path
from .consumers import ChatConsumer, NotificationConsumer, OnlineUsersConsumer

websocket_urlpatterns = [
    path('chat/<str:room_name>/', ChatConsumer.as_asgi()),
    path('notifications/', NotificationConsumer.as_asgi()),
    path('online-users/', OnlineUsersConsumer.as_asgi()),
]
