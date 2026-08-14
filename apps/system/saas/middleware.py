"""
SaaS 多租户中间件

解析「当前请求属于哪个租户」并注入 request.tenant / request.tenant_id，
供 IsTenantMember* 权限类与 TenantQuerysetMixin 使用。

解析顺序（显式请求信号优先，便于 SPA 切换租户 / 跨服务调用）：
  1) 请求头 X-Tenant-Id        —— SPA/跨服务首选，每请求显式指定
  2) JWT claim (tenant_id)     —— 登录时写入 token，无状态默认租户
  3) Session (current_tenant_id) —— 浏览器回退（switch_tenant 写入）

注意：JWT 在 DRF 鉴权阶段（dispatch）才会把 request.user 填上，
中间件运行于 process_request 时还拿不到 JWT 用户，因此此处**不依赖
request.user** 来解析租户——只负责「这个请求在聊哪个租户」。
真正的「用户是否该租户成员」由 IsTenantMember* 权限类在 has_permission
里校验（fail-closed）。Session 路径因已有已认证用户，额外做一次成员校验
（与原逻辑一致：非成员则清除 session 中的 current_tenant_id）。
"""
from django.utils.deprecation import MiddlewareMixin
from loguru import logger


class TenantMiddleware(MiddlewareMixin):
    """请求级租户上下文中间件"""

    def _resolve_tenant_id(self, request):
        """
        三源解析租户 ID，返回 (tenant_id, source) 或 (None, None)。
        source ∈ {'header', 'jwt', 'session'}，仅在需要区分时用到。
        """
        # 1) 显式请求头（SPA / 跨服务调用首选）
        header_tid = request.headers.get("X-Tenant-Id")
        if header_tid:
            return header_tid, "header"

        # 2) JWT claim（中间件阶段 DRF 尚未鉴权，需手动解码 Bearer）
        auth = request.headers.get("Authorization") or request.META.get(
            "HTTP_AUTHORIZATION", ""
        )
        if auth.startswith("Bearer "):
            raw = auth[7:].strip()
            if raw:
                try:
                    from rest_framework_simplejwt.tokens import AccessToken

                    claims = AccessToken(raw)
                    jwt_tid = claims.get("tenant_id")
                    if jwt_tid:
                        return str(jwt_tid), "jwt"
                except Exception:
                    # token 无效/过期/类型不符：静默回落，不阻断请求
                    pass

        # 3) Session（浏览器回退）
        return request.session.get("current_tenant_id"), "session"

    def _load_tenant(self, tenant_id):
        from .models import Tenant

        try:
            return Tenant.objects.filter(id=tenant_id).first()
        except Exception:
            return None

    def process_request(self, request):
        request.tenant = None
        request.tenant_id = None

        tenant_id, source = self._resolve_tenant_id(request)
        if not tenant_id:
            return

        tenant = self._load_tenant(tenant_id)
        if not tenant:
            return

        # 若请求已携带已认证用户（Session 路径），做一次成员校验；
        # JWT 路径用户在中间件阶段尚未鉴权，交由权限类校验，此处不拦截。
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            try:
                from .models import TenantMember

                user_role = getattr(user, "role", None)
                is_super = user.is_superuser or (
                    user_role
                    and getattr(user_role, "slug", None) in ("super-admin", "admin")
                )
                is_member = is_super or TenantMember.objects.filter(
                    tenant=tenant, user=user, is_active=True
                ).exists()
                if not is_member:
                    # 仅当来源是 session 时才清理 session，避免误清 JWT/头场景状态
                    if source == "session":
                        request.session.pop("current_tenant_id", None)
                        logger.warning(
                            f"用户 {user.username} 尝试访问租户 {tenant.name} 但无成员关系，已清除"
                        )
                    return
            except Exception:
                pass

        request.tenant = tenant
        request.tenant_id = str(tenant.id)

    def process_response(self, request, response):
        # 注入响应头方便前端感知当前租户
        if getattr(request, "tenant", None):
            response["X-Tenant-Id"] = str(request.tenant.id)
            response["X-Tenant-Name"] = request.tenant.name
        return response
