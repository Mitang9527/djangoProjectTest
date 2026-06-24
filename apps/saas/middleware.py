"""
SaaS 多租户中间件
从 Session 中读取当前活跃租户，注入 request.tenant。
"""
from django.utils.deprecation import MiddlewareMixin
from loguru import logger


class TenantMiddleware(MiddlewareMixin):
    """请求级租户上下文中间件"""

    def process_request(self, request):
        request.tenant = None
        request.tenant_id = None

        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return

        # 从 Session 读取当前租户 ID
        tenant_id = request.session.get('current_tenant_id')

        if tenant_id:
            from .models import Tenant, TenantMember
            try:
                tenant = Tenant.objects.get(id=tenant_id)
                # 验证用户是否是该租户的成员（管理员跳过）
                is_super = request.user.is_superuser or getattr(request.user, 'role', 'user') == 'admin'
                if is_super or TenantMember.objects.filter(
                    tenant=tenant, user=request.user, is_active=True
                ).exists():
                    request.tenant = tenant
                    request.tenant_id = str(tenant.id)
                    return
                else:
                    logger.warning(
                        f"用户 {request.user.username} 尝试访问租户 {tenant.name} 但无成员关系，已清除"
                    )
                    request.session.pop('current_tenant_id', None)
            except (Tenant.DoesNotExist, Exception):
                request.session.pop('current_tenant_id', None)

    def process_response(self, request, response):
        # 注入响应头方便前端感知
        if request.tenant:
            response['X-Tenant-Id'] = str(request.tenant.id)
            response['X-Tenant-Name'] = request.tenant.name
        return response
