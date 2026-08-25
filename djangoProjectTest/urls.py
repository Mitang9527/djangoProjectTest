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


def root_index(request):
    """根路径入口：返回 API 服务信息（纯后端，不渲染 Django 欢迎页）
    已摒弃
    """
    return JsonResponse({
        "service": "djangoProjectTest",
        "version": "v1",
        "endpoints": {
            "health": "/api/v1/health/",
            "ping": "/api/v1/core/ping/",
            "swagger": "/api/swagger/",
            "redoc": "/api/redoc/",
            "admin": "/admin/",
        },
    })

def discover_app_urls():
    """
    自动发现 apps/ 与 extensions/ 下的业务路由，并挂载到
    /api/<version>/<leaf>/（version 取自 settings.API_VERSIONS，默认 ['v1']）。

    版本迭代约定（路径版本化，URL 为唯一权威）：
    - 各版本默认复用 app 的 urls.py；
    - 若 app 提供了 <version>_urls.py（如 v2_urls.py），该版本优先用此模块，
      便于 app 级「只重写差异」的版本迭代；
    - 非 v1 版本若缺对应模块则优雅跳过，不影响其它版本与 v1。

    手动接线的 app（users/core/saas/apk_tool）不在此处发现。
    """
    import importlib

    urlpatterns = []
    seen_routes = set()

    # 手动接线的 app（按叶子 label）不在此自动发现，避免重复注册
    MANUAL_APPS = {'users', 'core', 'saas', 'apk_tool'}

    versions = list(getattr(settings, 'API_VERSIONS', ['v1']))

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

            for version in versions:
                route_path = f'api/{version}/{leaf}/'
                if route_path in seen_routes:
                    continue
                # v1 用 urls；vN 优先 <version>_urls（存在才用），否则跳过
                module = f'{mod}.urls' if version == 'v1' else f'{mod}.{version}_urls'
                if version != 'v1':
                    try:
                        importlib.import_module(module)
                    except ImportError:
                        continue
                seen_routes.add(route_path)
                urlpatterns.append(
                    path(route_path, include(module))
                )

    return urlpatterns

from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from system.core.views import AdminRequiredMixin
from framework.health.views import HealthView, ReadinessView
from django.views.debug import default_urlconf
# 创建带权限保护的视图类
class AdminOnlySpectacularAPIView(AdminRequiredMixin, SpectacularAPIView):
    pass

class AdminOnlySpectacularSwaggerView(AdminRequiredMixin, SpectacularSwaggerView):
    pass

class AdminOnlySpectacularRedocView(AdminRequiredMixin, SpectacularRedocView):
    pass

urlpatterns = [
    # 健康检查（Docker / 负载均衡器 / K8s 探活）
    # - api/v1/health/ : 轻量 DB 连通性
    # - healthz/       : 存活探针（framework.health，永远 200）
    # - readyz/        : 就绪探针（检查 DB/Cache/Broker，失败 503）
    path('api/v1/health/', health_check, name='health-check'),
    path('healthz/', HealthView.as_view(), name='healthz'),
    path('readyz/', ReadinessView.as_view(), name='readyz'),

    # 根路径：Django 原生欢迎页（default_urlconf 仅在 DEBUG 模式渲染）
    path('', default_urlconf, name='welcome'),

    # Prometheus 指标导出（仅限内网访问，需在 nginx/ingress 层限制）
    path('', include('django_prometheus.urls')),

    path('admin/', admin.site.urls),
    # DRF auth urls（框架约定，不随业务 API 版本化）
    path('api-auth/', include('rest_framework.urls')),

    # Swagger 文档（仅管理员可访问；文档端点不随业务 API 版本化）
    path('api/schema/', AdminOnlySpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/swagger/', AdminOnlySpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', AdminOnlySpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # ============ 业务 API 统一收口到 /api/v1/ ============
    # Users
    path('api/v1/users/', include('system.users.urls', namespace='users')),
    # SaaS 后台（页面 + API）
    path('api/v1/saas/', include('system.saas.urls')),
    # 核心平台（审计 / API Key / ping / 上传 / 演示登录 等）
    path('api/v1/core/', include('system.core.urls')),
]

# ============ 业务 API 版本迭代（受 settings.API_VERSIONS 控制）============
# 示例：users 提供 v2 接口（继承 v1，仅重写差异）。其它 app 按需提供
# <version>_urls 模块即可（自动发现会在 API_VERSIONS 含该版本时一并挂载）。
if 'v2' in getattr(settings, 'API_VERSIONS', ['v1']):
    urlpatterns += [
        path('api/v2/users/', include('system.users.v2_urls', namespace='users_v2')),
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
