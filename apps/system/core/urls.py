from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.views.debug import default_urlconf
from .views import (
    SystemStatusView, HealthCheckView, LivenessCheckView, ReadinessCheckView,
    FileUploadView, ImageUploadView, AuditLogViewSet, PingView, SecureInfoView,
    PingAuthView, ApiKeyViewSet
)
from .auth import DemoLoginView

app_name = 'core'

router = DefaultRouter()
router.register('audit-log', AuditLogViewSet, basename='audit-log')
router.register('api-keys', ApiKeyViewSet, basename='api-keys')

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
    # 对照演示：authentication_classes=[SlidingJWTAuthentication] 时的认证行为
    path('api/ping-auth/', PingAuthView.as_view(), name='ping-auth'),
    # 时效性密钥受保护接口（密钥校验通过才返回信息）
    path('api/secure-info/', SecureInfoView.as_view(), name='secure-info'),
    # API Key 生命周期管理（视图集，挂在 /api/api-keys/ 下；管理员专属签发，
    # 用 JWT 鉴权，不走全局请求签名校验；通配覆盖 detail / rotate 子路由）
    # 路由注册见上方 DefaultRouter（router.register('api-keys', ...)）


    # 全局演示登录（前后端联调用，生产需关闭 ALLOW_DEMO_LOGIN）
    path('api/demo-login/', DemoLoginView.as_view(), name='demo-login'),
]
