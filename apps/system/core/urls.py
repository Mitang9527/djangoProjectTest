"""核心平台路由。

挂载平台级 API 视图：健康检查、文件上传、API Key、审计日志、登录/操作日志、
数据字典、文件资产、菜单等。路由统一由项目根 djangoProjectTest/urls.py
以 /api/v1/core/ 前缀接入。
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .auth import DemoLoginView
from .views import (
    ApiKeyViewSet,
    AudioUploadView,
    AuditLogViewSet,
    DictItemViewSet,
    DictTypeViewSet,
    DocumentUploadView,
    FileAssetsUsageView,
    FileAssetViewSet,
    HealthCheckView,
    ImageUploadView,
    LivenessCheckView,
    LoginLogViewSet,
    MenuViewSet,
    MyMenusView,
    OperationLogViewSet,
    PingAuthView,
    PingView,
    PublicDictItemsView,
    ReadinessCheckView,
    SecureInfoView,
    SystemStatusView,
    TokenInfoView,
    VideoUploadView,
)

app_name = 'core'

router = DefaultRouter()
router.register('audit-log', AuditLogViewSet, basename='audit-log')
router.register('api-keys', ApiKeyViewSet, basename='api-keys')
router.register('logs/login', LoginLogViewSet, basename='login-log')
router.register('logs/operation', OperationLogViewSet, basename='operation-log')
router.register('dicts/types', DictTypeViewSet, basename='dict-type')
router.register('dicts/items', DictItemViewSet, basename='dict-item')
router.register('menus', MenuViewSet, basename='menu')
router.register('file-assets', FileAssetViewSet, basename='file-asset')

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('health/live/', LivenessCheckView.as_view(), name='health-live'),
    path('health/ready/', ReadinessCheckView.as_view(), name='health-ready'),
    path('system-status/', SystemStatusView.as_view(), name='system-status'),
    # 注意：file-assets/usage/ 必须先于 include(router.urls)，否则被 {pk} detail 路由吞掉
    path('file-assets/usage/', FileAssetsUsageView.as_view(), name='file-assets-usage'),
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

    # 字典公开读端点：按 code 读取字典项（登录即可，带 Redis 缓存）
    path('dicts/<str:code>/items/', PublicDictItemsView.as_view(), name='dict-items-by-code'),

    # 平台级动态菜单：管理 CRUD（menus，仅超管）+ 我的菜单（my-menus，按角色权限过滤）
    path('my-menus/', MyMenusView.as_view(), name='my-menus'),
]
