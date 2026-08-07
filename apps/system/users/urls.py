from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserRegisterView, UserLoginView, UserLogoutView, UserInfoView, UserListView,
    TestApiView,
    CustomTokenObtainPairView, CustomTokenRefreshView, JWTLogoutView, VerifyTokenView,
    UserManageViewSet, SystemRoleListView,
)

app_name = 'users'

# 用户管理 API Router
user_router = DefaultRouter()
user_router.register(r'manage', UserManageViewSet, basename='user-manage')

urlpatterns = [
    # 测试接口
    path('api/test/', TestApiView.as_view(), name='test-api'),
    
    # 系统角色 API
    path('system-roles/', SystemRoleListView.as_view(), name='system-roles'),
    
    # 注册 / 登录 API
    path('register/', UserRegisterView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),

    # API 接口
    path('api/list/', UserListView.as_view(), name='user-list'),

    # 其他
    path('logout/', UserLogoutView.as_view(), name='logout'),
    
    # 用户信息（合并路由以解决 Swagger 操作 ID 冲突）
    path('info/', UserInfoView.as_view(), name='info'),
    
    # =====================================================
    # JWT 认证接口
    # =====================================================
    path('api/jwt/login/', CustomTokenObtainPairView.as_view(), name='jwt-login'),
    path('api/jwt/refresh/', CustomTokenRefreshView.as_view(), name='jwt-refresh'),
    path('api/jwt/logout/', JWTLogoutView.as_view(), name='jwt-logout'),
    path('api/jwt/verify/', VerifyTokenView.as_view(), name='jwt-verify'),
    
    # 用户管理 API（供 SaaS 后台使用）
    path('api/', include(user_router.urls)),
]

# OIDC 单点登录路由（仅在启用时注册，避免未配置 / 未安装 mozilla-django-oidc 时报错）
from django.conf import settings
if getattr(settings, 'OIDC_ENABLED', False):
    from mozilla_django_oidc.views import OIDCAuthenticationRequestView
    from system.users.oidc import OIDCCallbackView, OIDCLogoutView
    urlpatterns += [
        # 浏览器访问此端点 -> 重定向到 IdP 授权页
        path('oidc/login/', OIDCAuthenticationRequestView.as_view(), name='oidc-login'),
        # IdP 授权后回调此端点 -> 签发 JWT 并跳回前端
        path('oidc/callback/', OIDCCallbackView.as_view(), name='oidc-callback'),
        # 登出（可选跳转 IdP 全局登出）
        path('oidc/logout/', OIDCLogoutView.as_view(), name='oidc-logout'),
    ]
