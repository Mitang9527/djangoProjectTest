"""
SaaS 多租户数据隔离 Mixin
ViewSet 混入后自动按 request.tenant 过滤查询集。
"""
from loguru import logger


class TenantQuerysetMixin:
    """
    DRF ViewSet 混入类：自动根据当前租户过滤数据。
    仅对具有 tenant 外键的模型生效。
    - 管理员无租户上下文时返回全部（用于全局后台管理）。
    - 普通用户按 request.tenant 过滤。
    """

    # 设置为 None 表示自动检测模型是否有 tenant 字段
    tenant_field = 'tenant'

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request

        # 管理员 / 拥有全局角色 / 无租户上下文 → 全局视图
        user_role = getattr(request.user, 'role', None)
        is_super = (request.user.is_superuser
                    or (user_role and user_role.slug in ['super-admin', 'admin'])
                    or getattr(request.user, 'global_role_id', None) is not None)
        if is_super and not getattr(request, 'tenant', None):
            return queryset

        # 有租户上下文 → 过滤
        tenant = getattr(request, 'tenant', None)
        if tenant and self.tenant_field:
            return queryset.filter(**{self.tenant_field: tenant})

        # 普通用户无租户上下文 → 空结果（无权查看全局）
        if not is_super and not tenant:
            logger.warning(f"用户 {request.user.username} 无租户上下文，返回空")
            return queryset.none()

        return queryset


class TenantChildQuerysetMixin(TenantQuerysetMixin):
    """
    适用于非直接关联 tenant 的模型（如 Role、TenantMember、Order 等）。
    通过 tenant 外键实现间接过滤。
    """
    tenant_field = 'tenant'
