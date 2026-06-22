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
    # 网页路由
    path('', DashboardView.as_view(), name='dashboard'),
    path('tenants/', TenantListView.as_view(), name='tenant-list'),
    path('members/', MemberListView.as_view(), name='member-list'),
    path('roles/', RoleListView.as_view(), name='role-list'),
    path('permissions/', PermissionListView.as_view(), name='permission-list'),
    path('plans/', PlanListView.as_view(), name='plan-list'),
    path('subscriptions/', SubscriptionListView.as_view(), name='subscription-list'),
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('invoices/', InvoiceListView.as_view(), name='invoice-list'),
    path('configs/', ConfigListView.as_view(), name='config-list'),
    # API 路由
    path('api/', include(router.urls)),
]
