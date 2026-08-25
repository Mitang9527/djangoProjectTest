"""
SaaS 后台管理系统 - 路由配置
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
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
    GlobalConfigViewSet,
    FeatureFlagViewSet,
    ConfigHistoryViewSet,
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
    get_config_value,
    get_all_configs,
    get_public_configs,
    set_config_value,
    reload_configs,
    check_feature_flag,
    get_user_features,
    toggle_feature_flag,
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
router.register(r'global-configs', GlobalConfigViewSet)
router.register(r'feature-flags', FeatureFlagViewSet)
router.register(r'config-history', ConfigHistoryViewSet)

urlpatterns = [
    # APK 工具 API 路由（apk_tool 嵌套在此）
    path('apk-tool/', include('apk_tool.urls')),
    # API 路由（router 注册的 plans / tenants / roles / orders ...）
    path('', include(router.urls)),
    path('me/permissions/', me_permissions, name='me-permissions'),
    path('me/tenants/', me_tenants, name='me-tenants'),
    path('me/switch-tenant/', switch_tenant, name='switch-tenant'),
    path('permissions/grouped/', permissions_grouped, name='permissions-grouped'),
    path('system/dashboard/', system_dashboard_api, name='system-dashboard-api'),
    path('system/logs/', system_logs_api, name='system-logs-api'),
    path('system/configs/', system_settings_config_api, name='system-settings-config-api'),
    path('system/backup/', system_backup_api, name='system-backup-api'),
    path('system/backup/list/', system_backup_list_api, name='system-backup-list-api'),
    path('export/', export_data, name='export-data'),
    path('export/models/', export_models, name='export-models'),
    # 网关管理 API
    path('gateway/dashboard/', gateway_dashboard_api, name='gateway-dashboard-api'),
    path('gateway/rules/', gateway_rules_list_api, name='gateway-rules-list-api'),
    path('gateway/rules/create/', gateway_rule_create_api, name='gateway-rule-create-api'),
    path('gateway/rules/<uuid:rule_id>/update/', gateway_rule_update_api, name='gateway-rule-update-api'),
    path('gateway/rules/<uuid:rule_id>/delete/', gateway_rule_delete_api, name='gateway-rule-delete-api'),
    path('gateway/rules/<uuid:rule_id>/toggle/', gateway_rule_toggle_api, name='gateway-rule-toggle-api'),
    # 缓存管理 API
    path('cache/stats/', cache_stats_api, name='cache-stats-api'),
    path('cache/invalidate/', cache_invalidate_api, name='cache-invalidate-api'),
    path('cache/warmup/', cache_warmup_api, name='cache-warmup-api'),
    path('cache/reset-stats/', cache_reset_stats_api, name='cache-reset-stats-api'),
    # DB 连接池管理 API
    path('db-pool/stats/', db_pool_stats_api, name='db-pool-stats-api'),
    path('db-pool/reset-stats/', db_pool_reset_stats_api, name='db-pool-reset-stats-api'),
    path('db-pool/reinit/', db_pool_reinit_api, name='db-pool-reinit-api'),
    
    # 配置中心 API
    path('config-center/get/', get_config_value, name='config-get-api'),
    path('config-center/all/', get_all_configs, name='config-all-api'),
    path('config-center/public/', get_public_configs, name='config-public-api'),
    path('config-center/set/', set_config_value, name='config-set-api'),
    path('config-center/reload/', reload_configs, name='config-reload-api'),
    
    # 特性开关 API
    path('feature-flags/check/', check_feature_flag, name='feature-check-api'),
    path('feature-flags/user/', get_user_features, name='feature-user-api'),
    path('feature-flags/<uuid:feature_id>/toggle/', toggle_feature_flag, name='feature-toggle-api'),
]
