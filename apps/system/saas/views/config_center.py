"""
SaaS 后台管理系统 — 配置中心 API 接口。
"""
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from ..models import GlobalConfig
from ..services import ConfigCenterService


@extend_schema(
    summary='Get config value',
    tags=['Config Center'],
    responses={200: {'type': 'object', 'properties': {
        'key': {'type': 'string'},
        'value': {},
        'exists': {'type': 'boolean'}
    }}}
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated])
def get_config_value(request):
    """获取单个配置值"""
    key = request.query_params.get('key', '')
    if not key:
        return Response({'detail': 'key 参数不能为空'}, status=400)
    exists = GlobalConfig.objects.filter(key=key, is_active=True).exists()

    return Response({
        'key': key,
        'value': value,
        'exists': exists
    })


@extend_schema(
    summary='Get all configs',
    tags=['Config Center'],
    responses={200: {'type': 'object', 'additionalProperties': {}}}
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated])
def get_all_configs(request):
    """获取所有配置（可选按分类过滤）"""
    category = request.query_params.get('category')
    configs = ConfigCenterService.get_all_configs(category=category)
    return Response(configs)


@extend_schema(
    summary='Get public configs',
    tags=['Config Center'],
    responses={200: {'type': 'object', 'additionalProperties': {}}}
)
@api_view(['GET'])
@drf_permission_classes([permissions.AllowAny])
def get_public_configs(request):
    """获取公开配置（无需认证）"""
    configs = ConfigCenterService.get_public_configs()
    return Response(configs)


@extend_schema(
    summary='Set config value',
    tags=['Config Center'],
    request={
        'application/json': {
            'type': 'object',
            'required': ['key', 'value'],
            'properties': {
                'key': {'type': 'string'},
                'value': {},
                'name': {'type': 'string', 'description': '新增时必填'},
                'description': {'type': 'string'},
                'category': {'type': 'string'},
                'config_type': {'type': 'string'},
            }
        }
    },
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated])
def set_config_value(request):
    """设置配置（新增或更新）"""
    key = request.data.get('key', '')
    value = request.data.get('value')
    name = request.data.get('name')
    description = request.data.get('description', '')
    category = request.data.get('category', 'system')
    config_type = request.data.get('config_type', 'string')

    if not key:
        return Response({'detail': 'key 参数不能为空'}, status=400)

    result = ConfigCenterService.set_config(
        key=key,
        value=value,
        user=request.user,
        name=name,
        description=description,
        category=category,
        config_type=config_type
    )

    if 'error' in result:
        return Response({'detail': result['error']}, status=400)

    return Response({
        'status': 'ok',
        'key': key,
        'value': value
    })


@extend_schema(
    summary='Reload configs',
    tags=['Config Center'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated])
def reload_configs(request):
    """强制刷新配置缓存"""
    result = ConfigCenterService.reload_configs()
    return Response(result)
