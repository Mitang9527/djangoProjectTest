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
from loguru import logger
from rest_framework.routers import DefaultRouter
from saas.views import (
    PlanViewSet,
    PlanFeatureViewSet,
    TenantViewSet,
    TenantSubscriptionViewSet,
    TenantConfigViewSet,
    PermissionViewSet,
    RoleViewSet,
    TenantMemberViewSet,
    OrderViewSet,
    InvoiceViewSet
)


def discover_app_urls():
    """
    自动发现 apps 目录下的所有路由（双层去重：app + route）
    """
    urlpatterns = []

    seen_apps = set()
    seen_routes = set()

    apps_dir = os.path.join(settings.BASE_DIR, 'apps')

    if not os.path.exists(apps_dir):
        return urlpatterns

    for app_name in os.listdir(apps_dir):
        app_path = os.path.join(apps_dir, app_name)
        urls_file = os.path.join(app_path, 'urls.py')

        if app_name in ['users', 'core', 'saas']:
            continue

        if app_name in seen_apps:
            continue

        if os.path.isdir(app_path) and os.path.exists(urls_file):

            route_path = f'api/{app_name}/'

            if route_path in seen_routes:
                continue

            seen_apps.add(app_name)
            seen_routes.add(route_path)

            urlpatterns.append(
                path(route_path, include(f'{app_name}.urls'))
            )

    return urlpatterns

from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from core.views import AdminRequiredMixin
from saas.views import DashboardView

# 创建带权限保护的视图类
class AdminOnlySpectacularAPIView(AdminRequiredMixin, SpectacularAPIView):
    pass

class AdminOnlySpectacularSwaggerView(AdminRequiredMixin, SpectacularSwaggerView):
    pass

class AdminOnlySpectacularRedocView(AdminRequiredMixin, SpectacularRedocView):
    pass

# 配置 SaaS API 路由
saas_router = DefaultRouter()
saas_router.register(r'plans', PlanViewSet)
saas_router.register(r'plan-features', PlanFeatureViewSet)
saas_router.register(r'tenants', TenantViewSet)
saas_router.register(r'tenant-subscriptions', TenantSubscriptionViewSet)
saas_router.register(r'tenant-configs', TenantConfigViewSet)
saas_router.register(r'permissions', PermissionViewSet)
saas_router.register(r'roles', RoleViewSet)
saas_router.register(r'tenant-members', TenantMemberViewSet)
saas_router.register(r'orders', OrderViewSet)
saas_router.register(r'invoices', InvoiceViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    # DRF auth urls
    path('api-auth/', include('rest_framework.urls')),
    
    # Swagger 文档 (仅管理员可访问)
    path('api/schema/', AdminOnlySpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/swagger/', AdminOnlySpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', AdminOnlySpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Users app urls
    path('api/users/', include('users.urls')),
    
    # SaaS app urls
    path('saas/', include('saas.urls')),
    
    # Core app urls
    path('', include('core.urls')),
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
