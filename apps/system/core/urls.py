from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.views.debug import default_urlconf
from .views import (
    SystemStatusView, HealthCheckView, LivenessCheckView, ReadinessCheckView,
    FileUploadView, ImageUploadView, AuditLogViewSet, PingView
)
from .auth import DemoLoginView

app_name = 'core'

router = DefaultRouter()
router.register('audit-log', AuditLogViewSet, basename='audit-log')

urlpatterns = [
    path('', default_urlconf, name='welcome'),
    path('health/', HealthCheckView.as_view(), name='health'),
    path('health/live/', LivenessCheckView.as_view(), name='health-live'),
    path('health/ready/', ReadinessCheckView.as_view(), name='health-ready'),
    path('system-status/', SystemStatusView.as_view(), name='system-status'),
    path('api/', include(router.urls)),
    # 文件上传相关路由
    path('api/upload/file/', FileUploadView.as_view(), name='upload-file'),
    path('api/upload/image/', ImageUploadView.as_view(), name='upload-image'),
    path('api/ping/', PingView.as_view(), name='ping'),
    # 全局演示登录（前后端联调用，生产需关闭 ALLOW_DEMO_LOGIN）
    path('api/demo-login/', DemoLoginView.as_view(), name='demo-login'),
]
