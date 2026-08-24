"""
健康检查 URL 配置。

在 ROOT_URLCONF 中按需接入：
    urlpatterns += [path("health/", include("framework.health.urls"))]
"""
from django.urls import path

from framework.health.views import HealthView, ReadinessView

app_name = "health"
urlpatterns = [
    path("healthz/", HealthView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),
]
