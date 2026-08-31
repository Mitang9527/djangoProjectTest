"""
SaaS 后台管理系统 — 租户切换 API。
"""
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from loguru import logger
from django.conf import settings

from ..services import TenantService
from framework.cache.view_cache import drf_cache_view, T_1_MINUTE, TAG_TENANT


@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated])
@drf_cache_view("me_tenants", timeout=T_1_MINUTE, tags=[TAG_TENANT])
def me_tenants(request):
    """返回当前用户可访问的租户列表"""
    try:
        tenants = TenantService.get_accessible_tenants(request.user)
        current_id = request.session.get('current_tenant_id')
        logger.debug(f"[SaaS] me_tenants — user={request.user.username}, count={len(tenants)}")
        return Response({
            "tenants": tenants,
            "current_tenant_id": current_id,
        })
    except Exception as e:
        import traceback as tb
        logger.error(f"[SaaS] me_tenants 异常 — user={request.user.username}: {e}\n{tb.format_exc()}")
        return Response({
            "tenants": [],
            "current_tenant_id": None,
            "detail": str(e),
            "traceback": tb.format_exc() if settings.DEBUG else None,
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated])
def switch_tenant(request):
    """切换当前活跃租户（传 null 清除上下文，回到管理员全量视图）。

    对齐参考项目 /tenants/switch：切换成功后重签 JWT——
    旧 access 立即失效（吊销对应 jti 会话），新 token 携带新 tenant_id claim。
    """
    tenant_id = request.data.get('tenant_id')
    # JWT 认证下 request.auth 为 AccessToken（含 jti）；API Key / Session 认证为 None
    access_token = getattr(request.auth, "payload", None) is not None and request.auth or None
    result = TenantService.switch_tenant(
        request.user, tenant_id, request.session,
        request=request, access_token=access_token,
    )
    if 'error' in result:
        return Response({"detail": result["error"]}, status=403)
    return Response(result)
