from django.urls import path
from django.contrib.auth import views as auth_views
from .views import (
    UserRegisterView, UserLoginView, UserLogoutView, UserInfoView, UserListView,
    UserProfileTemplateView, TestApiView,
    CustomTokenObtainPairView, CustomTokenRefreshView, JWTLogoutView, VerifyTokenView
)

app_name = 'users'

urlpatterns = [
    # 测试接口
    path('api/test/', TestApiView.as_view(), name='test-api'),
    
    # 统一路由：支持 GET (页面) 和 POST (逻辑)
    path('register/', UserRegisterView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),
    
    # 密码重置 (Django 内置视图)
    path('password-reset/', auth_views.PasswordResetView.as_view(
        success_url='/api/users/password-reset/done/',
        email_template_name='registration/password_reset_email.html'
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        success_url='/api/users/password-reset-complete/'
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    
    # API 接口
    path('api/list/', UserListView.as_view(), name='user-list'),
    
    # 其他
    path('profile/', UserProfileTemplateView.as_view(), name='profile'),
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
]
