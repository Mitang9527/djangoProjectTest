"""
SaaS 后台管理系统 — 视图包。

原 saas/views.py (1398 行) 已按职责拆分为:
  - page_views.py      — Django 模板页面视图 (DashboardView, TenantListView 等)
  - viewsets.py        — DRF ViewSets (PlanViewSet, TenantViewSet 等)
  - config_center.py   — 配置中心 API (get_config_value, set_config_value 等)
  - feature_flags.py   — 特性开关 API (check_feature_flag, toggle_feature_flag 等)
  - tenant.py          — 租户切换 API (me_tenants, switch_tenant)
  - system.py          — 系统管理 API (dashboard, logs, settings, backup, export)
  - gateway.py         — API 网关管理 API
  - cache.py           — 缓存管理 API
  - db_pool.py         — DB 连接池管理 API

此 __init__.py 向后兼容：所有公共符号通过 re-export 保持原有导入路径不变。
"""
from .cache import (
    cache_invalidate_api,
    cache_reset_stats_api,
    cache_stats_api,
    cache_warmup_api,
)
from .config_center import (
    delete_config_value,
    get_all_configs,
    get_config_groups,
    get_config_value,
    get_public_configs,
    reload_configs,
    set_config_value,
)
from .db_pool import (
    db_pool_reinit_api,
    db_pool_reset_stats_api,
    db_pool_stats_api,
)
from .feature_flags import (
    check_feature_flag,
    get_user_features,
    toggle_feature_flag,
)
from .gateway import (
    gateway_dashboard_api,
    gateway_rule_create_api,
    gateway_rule_delete_api,
    gateway_rule_toggle_api,
    gateway_rule_update_api,
    gateway_rules_list_api,
)
from .system import (
    export_data,
    export_models,
    system_backup_api,
    system_backup_list_api,
    system_dashboard_api,
    system_logs_api,
    system_settings_config_api,
)
from .tenant import (
    me_tenants,
    switch_tenant,
)
from .viewsets import (
    ConfigHistoryViewSet,
    DepartmentViewSet,
    FeatureFlagViewSet,
    GlobalConfigViewSet,
    InvoiceViewSet,
    OrderViewSet,
    PermissionViewSet,
    PlanFeatureViewSet,
    PlanViewSet,
    PostViewSet,
    RoleViewSet,
    TenantConfigViewSet,
    TenantMemberViewSet,
    TenantSubscriptionViewSet,
    TenantViewSet,
    me_permissions,
    permissions_grouped,
)

__all__ = [
    # ViewSets
    'PlanViewSet', 'PlanFeatureViewSet', 'TenantViewSet',
    'TenantSubscriptionViewSet', 'TenantConfigViewSet',
    'PermissionViewSet', 'RoleViewSet', 'DepartmentViewSet', 'PostViewSet',
    'TenantMemberViewSet',
    'OrderViewSet', 'InvoiceViewSet',
    'GlobalConfigViewSet', 'FeatureFlagViewSet', 'ConfigHistoryViewSet',
    'permissions_grouped', 'me_permissions',
    # Config center
    'get_config_value', 'get_all_configs', 'get_public_configs',
    'get_config_groups',
    'set_config_value', 'delete_config_value', 'reload_configs',
    # Feature flags
    'check_feature_flag', 'get_user_features', 'toggle_feature_flag',
    # Tenant
    'me_tenants', 'switch_tenant',
    # System
    'system_dashboard_api', 'system_logs_api', 'system_settings_config_api',
    'system_backup_api', 'system_backup_list_api',
    'export_data', 'export_models',
    # Gateway
    'gateway_dashboard_api', 'gateway_rules_list_api',
    'gateway_rule_create_api', 'gateway_rule_update_api',
    'gateway_rule_delete_api', 'gateway_rule_toggle_api',
    # Cache
    'cache_stats_api', 'cache_invalidate_api',
    'cache_warmup_api', 'cache_reset_stats_api',
    # DB pool
    'db_pool_stats_api', 'db_pool_reset_stats_api', 'db_pool_reinit_api',
]
