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
from .viewsets import (
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
    permissions_grouped,
    me_permissions,
)
from .config_center import (
    get_config_value,
    get_all_configs,
    get_public_configs,
    set_config_value,
    reload_configs,
)
from .feature_flags import (
    check_feature_flag,
    get_user_features,
    toggle_feature_flag,
)
from .tenant import (
    me_tenants,
    switch_tenant,
)
from .system import (
    system_dashboard_api,
    system_logs_api,
    system_settings_config_api,
    system_backup_api,
    system_backup_list_api,
    export_data,
    export_models,
)
from .gateway import (
    gateway_dashboard_api,
    gateway_rules_list_api,
    gateway_rule_create_api,
    gateway_rule_update_api,
    gateway_rule_delete_api,
    gateway_rule_toggle_api,
)
from .cache import (
    cache_stats_api,
    cache_invalidate_api,
    cache_warmup_api,
    cache_reset_stats_api,
)
from .db_pool import (
    db_pool_stats_api,
    db_pool_reset_stats_api,
    db_pool_reinit_api,
)

__all__ = [
    # ViewSets
    'PlanViewSet', 'PlanFeatureViewSet', 'TenantViewSet',
    'TenantSubscriptionViewSet', 'TenantConfigViewSet',
    'PermissionViewSet', 'RoleViewSet', 'TenantMemberViewSet',
    'OrderViewSet', 'InvoiceViewSet',
    'GlobalConfigViewSet', 'FeatureFlagViewSet', 'ConfigHistoryViewSet',
    'permissions_grouped', 'me_permissions',
    # Config center
    'get_config_value', 'get_all_configs', 'get_public_configs',
    'set_config_value', 'reload_configs',
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
