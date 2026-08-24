"""
framework.tenancy — 多租户上下文解析。

提供 TenantMiddleware：从 X-Tenant-Id 请求头（或可选 JWT claim）解析当前租户，
注入 ``request.tenant`` 与 ``contextvars``，供下游缓存键、行级隔离、限流等消费
（现有 cache / idempotency 已读取 ``request.tenant``，但此前没有生产它的中间件）。

解析失败 / 未提供租户时 ``request.tenant`` 设为 None，安全降级，不影响单租户场景。

接入（可选，默认不启用，避免改变现有请求流）：
    # djangoProjectTest/settings/base.py 的 MIDDLEWARE 列表末尾追加
    MIDDLEWARE += ['framework.tenancy.middleware.TenantMiddleware']
"""
from framework.tenancy.middleware import TenantMiddleware, get_current_tenant

__all__ = ["TenantMiddleware", "get_current_tenant"]
