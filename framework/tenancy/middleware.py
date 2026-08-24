"""
多租户解析中间件。

解析优先级：
    1. 请求头 ``X-Tenant-Id``（前端登录后显式携带，最可靠）
    2. 请求头 ``X-Tenant``（兼容别名）
    3. 已在认证层写入 ``request.tenant_id`` 的属性（如 JWT 中间件）
查到 ACTIVE 租户则注入 ``request.tenant`` + contextvars；否则为 None（降级）。

为兼容 Django 测试 / 导入期不强制依赖 ORM，Tenant 模型延迟导入。
"""
import contextvars
import uuid
from typing import Optional

# 进程内当前租户（供视图 / ORM 包装 / 缓存键读取，避免层层传参）
_tenant_var: contextvars.ContextVar = contextvars.ContextVar("tenant", default=None)


def get_current_tenant():
    """返回当前上下文的 Tenant 实例（无租户时为 None）。"""
    return _tenant_var.get()


class TenantMiddleware:
    """将当前租户注入 request 与 contextvars。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = self._resolve(request)
        token = _tenant_var.set(tenant)
        try:
            request.tenant = tenant
            return self.get_response(request)
        finally:
            _tenant_var.reset(token)

    def _resolve(self, request) -> Optional[object]:
        tenant_id = (
            request.META.get("HTTP_X_TENANT_ID")
            or request.META.get("HTTP_X_TENANT")
            or getattr(request, "tenant_id", None)
        )
        if not tenant_id:
            return None
        return _load_tenant(tenant_id)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # 允许路由 URL 中直接声明 tenant_id（如 /api/tenants/<id>/...）
        tid = view_kwargs.get("tenant_id") or view_kwargs.get("tenant_pk")
        if tid and not getattr(request, "tenant", None):
            request.tenant = _load_tenant(tid)
        return None


# 轻量进程内缓存，避免同一进程高频查同租户（租户元数据变更不频繁）
_cache: dict = {}


def _load_tenant(tenant_id) -> Optional[object]:
    try:
        from django.db.models import Q

        from system.saas.models import Tenant

        cached = _cache.get(tenant_id)
        if cached is not None:
            return cached

        try:
            uuid.UUID(str(tenant_id))
            q = Q(id=tenant_id)
        except (ValueError, AttributeError, TypeError):
            q = Q(slug=tenant_id)

        tenant = Tenant.objects.filter(q, status=Tenant.Status.ACTIVE).first()
        if tenant is not None:
            _cache[tenant_id] = tenant
        return tenant
    except Exception:
        # 任何异常（DB 未就绪 / 模型未迁移）都不应阻断请求
        return None


def clear_tenant_cache() -> None:
    """测试或租户变更后清空缓存。"""
    _cache.clear()
