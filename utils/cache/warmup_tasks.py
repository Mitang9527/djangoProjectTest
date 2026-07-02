"""
缓存预热任务注册

用法: python manage.py cache_warmup
"""
from django.core.cache import cache
from loguru import logger

from utils.cache.cache_manager import register_warmup


@register_warmup("permission_slugs")
def warmup_permission_slugs():
    """预热权限 slug 列表"""
    from saas.permission_registry import ALL_PERMISSION_SLUGS
    cache.set("warmup:permission_slugs", ALL_PERMISSION_SLUGS, timeout=60 * 60 * 24)
    logger.info(f"[Warmup] 权限 slug 预热: {len(ALL_PERMISSION_SLUGS)} 条")


@register_warmup("active_tenants")
def warmup_active_tenants():
    """预热活跃租户列表"""
    from saas.models import Tenant
    tenants = list(
        Tenant.objects.filter(status='active')
        .values('id', 'name', 'slug')
    )
    cache.set("warmup:active_tenants", tenants, timeout=60 * 5)
    logger.info(f"[Warmup] 活跃租户预热: {len(tenants)} 个")


@register_warmup("active_roles")
def warmup_active_roles():
    """预热活跃角色列表"""
    from saas.models import Role
    roles = list(
        Role.objects.filter(is_active=True)
        .values('id', 'name', 'slug', 'tenant_id', 'is_system')
    )
    cache.set("warmup:active_roles", roles, timeout=60 * 5)
    logger.info(f"[Warmup] 活跃角色预热: {len(roles)} 个")
