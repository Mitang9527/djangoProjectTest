"""通知服务路由。

暴露健康检查与通知入队两个 HTTP 入口；正常链路走 RabbitMQ（主平台 → 本服务
worker），HTTP 入口仅作内部触发/调试。
"""
from django.urls import path

from notice_app.views import HealthView, NotifyView

urlpatterns = [
    path("api/health/", HealthView.as_view()),
    path("api/notice/notify/", NotifyView.as_view()),
]
