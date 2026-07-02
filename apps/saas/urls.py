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
    SystemDashboardView,
    SystemLogsView,
    SystemSettingsView,
    GatewayDashboardView,
    GatewayRulesView,
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
    permissions_grouped,
    system_dashboard_api,
    system_logs_api,
    system_settings_config_api,
    system_backup_api,
    system_backup_list_api,
    export_data,
    export_models,
    gateway_dashboard_api,
    gateway_rules_list_api,
    gateway_rule_create_api,
    gateway_rule_update_api,
    gateway_rule_delete_api,
    gateway_rule_toggle_api,
    cache_stats_api,
    cache_invalidate_api,
    cache_warmup_api,
    cache_reset_stats_api,
    db_pool_stats_api,
    db_pool_reset_stats_api,
    db_pool_reinit_api,
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
    path('system/dashboard/', SystemDashboardView.as_view(), name='system-dashboard'),
    path('system/logs/', SystemLogsView.as_view(), name='system-logs'),
    path('system/settings/', SystemSettingsView.as_view(), name='system-settings'),
    # 网关管理页面
    path('gateway/', GatewayDashboardView.as_view(), name='gateway-dashboard'),
    path('gateway/rules/', GatewayRulesView.as_view(), name='gateway-rules'),
    # API 路由
    path('api/', include(router.urls)),
    path('api/me/permissions/', me_permissions, name='me-permissions'),
    path('api/me/tenants/', me_tenants, name='me-tenants'),
    path('api/me/switch-tenant/', switch_tenant, name='switch-tenant'),
    path('api/permissions/grouped/', permissions_grouped, name='permissions-grouped'),
    path('api/system/dashboard/', system_dashboard_api, name='system-dashboard-api'),
    path('api/system/logs/', system_logs_api, name='system-logs-api'),
    path('api/system/configs/', system_settings_config_api, name='system-settings-config-api'),
    path('api/system/backup/', system_backup_api, name='system-backup-api'),
    path('api/system/backup/list/', system_backup_list_api, name='system-backup-list-api'),
    path('api/export/', export_data, name='export-data'),
    path('api/export/models/', export_models, name='export-models'),
    # 网关管理 API
    path('api/gateway/dashboard/', gateway_dashboard_api, name='gateway-dashboard-api'),
    path('api/gateway/rules/', gateway_rules_list_api, name='gateway-rules-list-api'),
    path('api/gateway/rules/create/', gateway_rule_create_api, name='gateway-rule-create-api'),
    path('api/gateway/rules/<uuid:rule_id>/update/', gateway_rule_update_api, name='gateway-rule-update-api'),
    path('api/gateway/rules/<uuid:rule_id>/delete/', gateway_rule_delete_api, name='gateway-rule-delete-api'),
    path('api/gateway/rules/<uuid:rule_id>/toggle/', gateway_rule_toggle_api, name='gateway-rule-toggle-api'),
    # 缓存管理 API
    path('api/cache/stats/', cache_stats_api, name='cache-stats-api'),
    path('api/cache/invalidate/', cache_invalidate_api, name='cache-invalidate-api'),
    path('api/cache/warmup/', cache_warmup_api, name='cache-warmup-api'),
    path('api/cache/reset-stats/', cache_reset_stats_api, name='cache-reset-stats-api'),
    # DB 连接池管理 API
    path('api/db-pool/stats/', db_pool_stats_api, name='db-pool-stats-api'),
    path('api/db-pool/reset-stats/', db_pool_reset_stats_api, name='db-pool-reset-stats-api'),
    path('api/db-pool/reinit/', db_pool_reinit_api, name='db-pool-reinit-api'),
]
