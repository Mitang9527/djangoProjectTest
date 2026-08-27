"""
SaaS 后台管理系统 — 缓存管理 API。
"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from ..permissions import SystemDashboardPermission
from ..services import CacheService


@extend_schema(
    summary="缓存命中率统计",
    description="返回缓存命中/未命中/写入/失效计数和命中率",
    tags=['缓存管理'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_stats_api(request):
    """返回当前进程的缓存命中率统计"""
    return Response(CacheService.get_stats())


@extend_schema(
    summary="缓存失效",
    description="按标签批量失效缓存。支持: dashboard, permissions, tenant, export, gateway",
    tags=['缓存管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_invalidate_api(request):
    """按标签批量失效缓存"""
    tag = request.data.get('tag', '')
    if not tag:
        return Response({"detail": "请提供 tag 参数"}, status=400)
    result = CacheService.invalidate_by_tag(tag)
    if 'error' in result:
        return Response({"detail": result["error"]}, status=400)
    return Response({"count": result["count"]})


@extend_schema(
    summary="缓存预热",
    description="执行所有已注册的预热函数",
    tags=['缓存管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_warmup_api(request):
    """触发缓存预热"""
    result = CacheService.warmup_all()
    return Response(result)


@extend_schema(
    summary="重置缓存统计",
    tags=['缓存管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_reset_stats_api(request):
    """重置缓存命中率统计"""
    result = CacheService.reset_stats()
    return Response(result)
