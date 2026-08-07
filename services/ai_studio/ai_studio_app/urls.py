"""AI 创作工作室路由（由根路由挂载于 /api/v1/）。"""
from django.urls import path

from .views import GenerateView, QuotaView, TaskListView

urlpatterns = [
    path("generate/", GenerateView.as_view(), name="ai-generate"),
    path("quota/", QuotaView.as_view(), name="ai-quota"),
    path("tasks/", TaskListView.as_view(), name="ai-tasks"),
]
