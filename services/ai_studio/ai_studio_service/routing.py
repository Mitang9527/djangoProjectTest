"""AI 服务 WebSocket 路由。"""
from django.urls import path

from ai_studio_app import consumers

websocket_urlpatterns = [
    path("ws/ai-studio/<uuid:task_id>/", consumers.AiStudioTaskConsumer.as_asgi()),
]
