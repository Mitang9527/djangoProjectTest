"""
URL configuration for djangoProjectTest project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.db import connection
from loguru import logger


def health_check(request):
    """Docker 健康检查端点，检查数据库连通性"""
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    status = 200 if db_ok else 503
    return JsonResponse({
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
    }, status=status)


def discover_app_urls():
    """
    自动发现 apps/ 与 extensions/ 目录下的所有路由（支持分类子目录，如
    apps/system/、apps/business/）。
    路由前缀使用 app 叶子名（例如 api/ai_studio/），但 include 使用完整点分
    模块路径（例如 business.ai_studio.urls），保证分类移动后 URL 保持稳定。
    """
    urlpatterns = []

    seen_routes = set()

    # 手动接线的 app（按叶子 label）不在此自动发现，避免重复注册
    MANUAL_APPS = {'users', 'core', 'saas', 'apk_tool'}

    scan_dirs = [
        os.path.join(settings.BASE_DIR, 'apps'),
        os.path.join(settings.BASE_DIR, 'extensions'),
    ]
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for root, dirs, files in os.walk(scan_dir):
            depth = root[len(scan_dir):].count(os.sep)
            if depth > 2:
                dirs[:] = []   # 超过最大深度则剪枝
                continue
            if 'urls.py' not in files:
                continue

            rel = os.path.relpath(root, scan_dir)
            mod = rel.replace(os.sep, '.')
            leaf = mod.split('.')[-1]

            if leaf in MANUAL_APPS:
                continue

            route_path = f'api/{leaf}/'
            if route_path in seen_routes:
                continue
            seen_routes.add(route_path)

            urlpatterns.append(
                path(route_path, include(f'{mod}.urls'))
            )

    return urlpatterns

from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from system.core.views import AdminRequiredMixin
from framework.health.views import HealthView, ReadinessView
# 创建带权限保护的视图类
class AdminOnlySpectacularAPIView(AdminRequiredMixin, SpectacularAPIView):
    pass

class AdminOnlySpectacularSwaggerView(AdminRequiredMixin, SpectacularSwaggerView):
    pass

class AdminOnlySpectacularRedocView(AdminRequiredMixin, SpectacularRedocView):
    pass

urlpatterns = [
    # 健康检查（Docker / 负载均衡器使用，无需认证）
    # - api/health/  : 轻量 DB 连通性（原端点，向后兼容）
    # - healthz/     : 存活探针（framework.health，永远 200）
    # - readyz/      : 就绪探针（检查 DB/Cache/Broker，失败 503）
    path('api/health/', health_check, name='health-check'),
    path('healthz/', HealthView.as_view(), name='healthz'),
    path('readyz/', ReadinessView.as_view(), name='readyz'),

    # Prometheus 指标导出（仅限内网访问，需在 nginx/ingress 层限制）
    path('', include('django_prometheus.urls')),

    path('admin/', admin.site.urls),
    # DRF auth urls
    path('api-auth/', include('rest_framework.urls')),
    
    # Swagger 文档 (仅管理员可访问)
    path('api/schema/', AdminOnlySpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/swagger/', AdminOnlySpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', AdminOnlySpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Users app urls
    path('api/users/', include('system.users.urls', namespace='users')),

    # SaaS app urls (pages + API)
    path('saas/', include('system.saas.urls')),

    # API v1 — 向前兼容的新前缀 (与旧路由并行，逐步迁移)
    path('api/v1/users/', include('system.users.urls', namespace='users_v1')),

    # Core app urls
    path('', include('system.core.urls')),
]

# 合并自动发现的路由（排除已手动添加的）
urlpatterns += discover_app_urls()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # Django Debug Toolbar
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include(debug_toolbar.urls)),
        ] + urlpatterns
