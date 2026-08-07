"""独立服务根路由。"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include


def health(request):
    """轻量健康检查（K8s/Docker 探针可用）。"""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include("ai_studio_app.urls")),
]
