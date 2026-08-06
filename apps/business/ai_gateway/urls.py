"""AI 网关路由（由主路由自动发现注册为 /api/ai_gateway/）。"""
from django.urls import path

from .views import GenerateView, TaskStatusView

urlpatterns = [
    path("generate/", GenerateView.as_view(), name="ai-gateway-generate"),
    path("tasks/<uuid:task_id>/", TaskStatusView.as_view(), name="ai-gateway-task-status"),
]
