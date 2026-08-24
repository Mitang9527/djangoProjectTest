"""
framework.health — Kubernetes / Docker 风格健康检查探针。

提供两个标准端点：
    GET /healthz   存活探针（liveness）：进程在即返回 200，不依赖任何外部资源。
    GET /readyz    就绪探针（readiness）：检查 DB / Cache / Broker 等依赖，
                   全部通过返回 200，任一失败返回 503。

检查逻辑复用 framework.log_utils.service_banner 的同一批底层 checker，
与健康检查共用一套"依赖是否就绪"的判断，避免重复实现。

接入方式（可选，默认不自动挂接，避免改动现有路由）：
    # djangoProjectTest/urls.py
    from django.urls import include
    urlpatterns += [path("health/", include("framework.health.urls"))]
"""
from framework.health.views import HealthView, ReadinessView
from framework.health import checks

__all__ = ["HealthView", "ReadinessView", "checks"]
