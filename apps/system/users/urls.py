from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserRegisterView, UserLoginView, UserLogoutView, UserInfoView, UserListView,
    TestApiView,
    CustomTokenObtainPairView, CustomTokenRefreshView, JWTLogoutView, VerifyTokenView,
    UserManageViewSet, SystemRoleListView,
    MfaStatusView, MfaSetupView, MfaConfirmView, MfaDisableView, MfaRecoveryView,
)
from .qr_login import QRLoginCreateView, QRLoginPollView, QRLoginConfirmView
from .sessions import SessionViewSet
from .change_password import ChangePasswordView
from .password_reset import PasswordResetRequestView, PasswordResetConfirmView
from .oauth2 import OAuth2AuthorizeView, OAuth2CallbackView, OAuth2BindView

app_name = 'users'

# 用户管理 API Router
user_router = DefaultRouter()
user_router.register(r'manage', UserManageViewSet, basename='user-manage')

# 会话管理 API Router（列表 / 踢单设备 / 踢其余）
session_router = DefaultRouter()
session_router.register(r'sessions', SessionViewSet, basename='session')

urlpatterns = [
    # 测试接口
    path('test/', TestApiView.as_view(), name='test-api'),
    
    # 系统角色 API
    path('system-roles/', SystemRoleListView.as_view(), name='system-roles'),
    
    # 注册 / 登录 API
    path('register/', UserRegisterView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),

    # API 接口
    path('list/', UserListView.as_view(), name='user-list'),

    # 其他
    path('logout/', UserLogoutView.as_view(), name='logout'),
    
    # 用户信息（合并路由以解决 Swagger 操作 ID 冲突）
    path('info/', UserInfoView.as_view(), name='info'),
    
    # =====================================================
    # JWT 认证接口
    # =====================================================
    path('jwt/login/', CustomTokenObtainPairView.as_view(), name='jwt-login'),
    path('jwt/refresh/', CustomTokenRefreshView.as_view(), name='jwt-refresh'),
    path('jwt/logout/', JWTLogoutView.as_view(), name='jwt-logout'),
    path('jwt/verify/', VerifyTokenView.as_view(), name='jwt-verify'),

    # =====================================================
    # MFA 双因子认证接口
    # =====================================================
    path('mfa/status/', MfaStatusView.as_view(), name='mfa-status'),
    path('mfa/setup/', MfaSetupView.as_view(), name='mfa-setup'),
    path('mfa/confirm/', MfaConfirmView.as_view(), name='mfa-confirm'),
    path('mfa/disable/', MfaDisableView.as_view(), name='mfa-disable'),
    path('mfa/recovery/', MfaRecoveryView.as_view(), name='mfa-recovery'),
    
    # =====================================================
    # QR 扫码登录（Redis CAS 状态机）
    # =====================================================
    path('qr-login/tickets/', QRLoginCreateView.as_view(), name='qr-login-create'),
    path('qr-login/tickets/<str:ticket_id>/', QRLoginPollView.as_view(), name='qr-login-poll'),
    path('qr-login/tickets/<str:ticket_id>/confirm/', QRLoginConfirmView.as_view(), name='qr-login-confirm'),

    # =====================================================
    # 账号安全：自助修改密码 + 会话管理
    # =====================================================
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),

    # 找回密码（邮箱重置，匿名 + 防枚举 + IP/email 双维度限流）
    path('password/reset/request/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password/reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),

    # =====================================================
    # OAuth2 第三方登录（Authorization Code + PKCE）
    # =====================================================
    path('oauth/<str:provider>/authorize/', OAuth2AuthorizeView.as_view(), name='oauth2-authorize'),
    path('oauth/<str:provider>/callback/', OAuth2CallbackView.as_view(), name='oauth2-callback'),
    path('oauth/<str:provider>/bind/', OAuth2BindView.as_view(), name='oauth2-bind'),

    # 用户管理 API（供 SaaS 后台使用）
    path('', include(user_router.urls)),
    # 会话管理 API
    path('', include(session_router.urls)),
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
