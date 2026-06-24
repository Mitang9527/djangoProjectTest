"""
SaaS 后台管理系统 - 路由配置
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DashboardView,
    TenantListView,
    MemberListView,
    RoleListView,
    PermissionListView,
    PlanListView,
    SubscriptionListView,
    OrderListView,
    InvoiceListView,
    ConfigListView,
    SystemUserListView,
    PlanViewSet,
    PlanFeatureViewSet,
    TenantViewSet,
    TenantSubscriptionViewSet,
    TenantConfigViewSet,
    PermissionViewSet,
    RoleViewSet,
    TenantMemberViewSet,
    OrderViewSet,
    InvoiceViewSet,
    me_permissions,
    me_tenants,
    switch_tenant,
)

app_name = 'saas'

router = DefaultRouter()
router.register(r'plans', PlanViewSet)
router.register(r'plan-features', PlanFeatureViewSet)
router.register(r'tenants', TenantViewSet)
router.register(r'tenant-subscriptions', TenantSubscriptionViewSet)
router.register(r'tenant-configs', TenantConfigViewSet)
router.register(r'permissions', PermissionViewSet)
router.register(r'roles', RoleViewSet)
router.register(r'tenant-members', TenantMemberViewSet)
router.register(r'orders', OrderViewSet)
router.register(r'invoices', InvoiceViewSet)

urlpatterns = [
    # 网页路由（name 统一加 -page 后缀，避免与 DRF Router 自动生成的 xxx-list 冲突）
    path('', DashboardView.as_view(), name='dashboard'),
    path('tenants/', TenantListView.as_view(), name='tenant-page'),
    path('members/', MemberListView.as_view(), name='member-page'),
    path('roles/', RoleListView.as_view(), name='role-page'),
    path('permissions/', PermissionListView.as_view(), name='permission-page'),
    path('plans/', PlanListView.as_view(), name='plan-page'),
    path('subscriptions/', SubscriptionListView.as_view(), name='subscription-page'),
    path('orders/', OrderListView.as_view(), name='order-page'),
    path('invoices/', InvoiceListView.as_view(), name='invoice-page'),
    path('configs/', ConfigListView.as_view(), name='config-page'),
    path('users/', SystemUserListView.as_view(), name='system-user-page'),
    # API 路由
    path('api/', include(router.urls)),
    path('api/me/permissions/', me_permissions, name='me-permissions'),
    path('api/me/tenants/', me_tenants, name='me-tenants'),
    path('api/me/switch-tenant/', switch_tenant, name='switch-tenant'),
]
