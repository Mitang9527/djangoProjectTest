from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SystemStatusView, HealthCheckView, LivenessCheckView, ReadinessCheckView,
    DocumentUploadView, ImageUploadView, VideoUploadView, AudioUploadView, TokenInfoView,
    AuditLogViewSet, PingView, SecureInfoView,
    PingAuthView, ApiKeyViewSet
)
from .auth import DemoLoginView

app_name = 'core'

router = DefaultRouter()
router.register('audit-log', AuditLogViewSet, basename='audit-log')
router.register('api-keys', ApiKeyViewSet, basename='api-keys')

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('health/live/', LivenessCheckView.as_view(), name='health-live'),
    path('health/ready/', ReadinessCheckView.as_view(), name='health-ready'),
    path('system-status/', SystemStatusView.as_view(), name='system-status'),
    path('', include(router.urls)),
    # 文件上传相关路由（按资源类型拆分为四种独立接口，各存独立目录）
    path('upload/file/', DocumentUploadView.as_view(), name='upload-file'),
    path('upload/image/', ImageUploadView.as_view(), name='upload-image'),
    path('upload/video/', VideoUploadView.as_view(), name='upload-video'),
    path('upload/audio/', AudioUploadView.as_view(), name='upload-audio'),
    # JWT access token 信息查询（需登录，免签名校验）
    path('token/info/', TokenInfoView.as_view(), name='token-info'),


    path('ping/', PingView.as_view(), name='ping'),
    # 对照演示：authentication_classes=[SlidingJWTAuthentication] 时的认证行为
    path('ping-auth/', PingAuthView.as_view(), name='ping-auth'),
    # 时效性密钥受保护接口（密钥校验通过才返回信息）
    path('secure-info/', SecureInfoView.as_view(), name='secure-info'),
    # API Key 生命周期管理（视图集，挂在 /api/v1/core/api-keys/ 下；管理员专属签发，
    # 用 JWT 鉴权，不走全局请求签名校验；通配覆盖 detail / rotate 子路由）
    # 路由注册见上方 DefaultRouter（router.register('api-keys', ...)）


    # 全局演示登录（前后端联调用，生产需关闭 ALLOW_DEMO_LOGIN）
    path('demo-login/', DemoLoginView.as_view(), name='demo-login'),
]
