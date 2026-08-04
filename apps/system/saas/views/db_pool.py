"""
SaaS 后台管理系统 — DB 连接池管理 API。
"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from ..permissions import SystemDashboardPermission, SystemManagePermission


@extend_schema(
    summary="DB 连接池运行指标",
    description="返回所有 alias 的池大小、活跃/空闲、命中率、超时数、错误数等。",
    tags=['系统管理'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def db_pool_stats_api(request):
    """获取所有连接池的运行指标"""
    from framework.db import pool_manager, is_patched
    stats = pool_manager.all_stats()
    return Response({
        'patched': is_patched(),
        'pools': stats,
    })


@extend_schema(
    summary="重置 DB 连接池指标",
    tags=['系统管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def db_pool_reset_stats_api(request):
    """清空所有池的指标计数器（不关闭池）"""
    from framework.db.metrics import reset_all_metrics
    reset_all_metrics()
    return Response({'detail': 'DB 连接池指标已重置'})


@extend_schema(
    summary="关闭并重建 DB 连接池",
    description="紧急情况下用于强制重连（如服务端连接被异常回收）。",
    tags=['系统管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemManagePermission])
def db_pool_reinit_api(request):
    """关闭所有池并重新初始化（高危操作）"""
    from framework.db import pool_manager
    pool_manager.close_all()
    n = pool_manager.init_pools()
    return Response({
        'initialized': n,
    })
