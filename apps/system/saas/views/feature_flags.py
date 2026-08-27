"""
SaaS 后台管理系统 — 特性开关 API 接口。
"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from ..services import FeatureFlagService


@extend_schema(
    summary='Check feature flag',
    tags=['Feature Flag'],
    responses={200: {'type': 'object', 'properties': {
        'key': {'type': 'string'},
        'enabled': {'type': 'boolean'}
    }}}
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated])
def check_feature_flag(request):
    """检查特性开关是否启用"""
    key = request.query_params.get('key', '')
    if not key:
        return Response({"detail": "key 参数不能为空"}, status=400)

    tenant = getattr(request, 'tenant', None)
    enabled = FeatureFlagService.is_enabled(key, request.user, tenant)

    return Response({
        "key": key,
        "enabled": enabled
    })


@extend_schema(
    summary='Get user feature flags',
    tags=['Feature Flag'],
    responses={200: {'type': 'object', 'additionalProperties': {'type': 'boolean'}}}
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated])
def get_user_features(request):
    """获取当前用户所有可用的特性开关"""
    tenant = getattr(request, 'tenant', None)
    features = FeatureFlagService.get_user_features(request.user, tenant)
    return Response(features)


@extend_schema(
    summary='Toggle feature flag status',
    tags=['Feature Flag'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated])
def toggle_feature_flag(request, feature_id):
    """切换特性开关状态"""
    result = FeatureFlagService.toggle_status(feature_id, request.user)
    if 'error' in result:
        return Response({"detail": result["error"]}, status=404)
    return Response(result)
