"""
users 应用 v2 路由（API 版本迭代示例）。

约定：
- v2 端点挂载在 /api/v2/users/ 下，由主 urls.py 在 settings.API_VERSIONS
  含 'v2' 时 include 此模块。
- 版本差异通过 ViewSet / View 继承 v1 实现，本文件只声明「与 v1 不同的路由」，
  未列于此的路由应继续走 /api/v1/users/，保证向后兼容。
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserManageViewSetV2

app_name = 'users_v2'

# v2 用户管理（继承 v1 的 UserManageViewSet，仅重写差异）
user_router_v2 = DefaultRouter()
user_router_v2.register(r'manage', UserManageViewSetV2, basename='user-manage-v2')

urlpatterns = [
    # 用户管理 v2（供 SaaS 后台使用）
    path('', include(user_router_v2.urls)),
]
