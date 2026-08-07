"""
SaaS 后台管理系统 — API 网关管理接口。
"""
import re as _re

from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from ..permissions import HasTenantPermission
from ..models import APILimitRule
from ..services import GatewayService


@extend_schema(
    summary="获取网关概览统计数据",
    description="返回当前限流规则数量、活跃规则数、最近拦截统计",
    tags=['API 网关'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_dashboard_api(request):
    """网关仪表盘数据"""
    return Response(GatewayService.get_dashboard())


@extend_schema(
    summary="列出所有限流规则",
    tags=['API 网关'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rules_list_api(request):
    """列出所有限流规则"""
    return Response({'rules': GatewayService.list_rules()})


@extend_schema(
    summary="创建限流规则",
    tags=['API 网关'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_create_api(request):
    """创建新的限流规则"""
    name = request.data.get('name', '').strip()
    url_pattern = request.data.get('url_pattern', '').strip()
    throttle_type = request.data.get('throttle_type', 'ip')
    rate = request.data.get('rate', '100/h')
    is_active = request.data.get('is_active', True)
    use_regex = request.data.get('use_regex', False)
    priority = request.data.get('priority', 0)
    description = request.data.get('description', '')

    if not name:
        return Response({'detail': '规则名称不能为空'}, status=400)
    if not url_pattern:
        return Response({'detail': 'URL 模式不能为空'}, status=400)

    valid_types = [t[0] for t in APILimitRule.RuleType.choices]
    if throttle_type not in valid_types:
        return Response({'detail': f'无效的限流类型，可选: {", ".join(valid_types)}'}, status=400)

    if not _re.match(r'^\d+/(s|m|h|d)$', rate):
        return Response({'detail': '速率格式无效，示例: 100/h'}, status=400)

    rule = APILimitRule.objects.create(
        name=name,
        url_pattern=url_pattern,
        throttle_type=throttle_type,
        rate=rate,
        is_active=is_active,
        use_regex=use_regex,
        priority=priority,
        description=description,
    )

    return Response({
        'id': str(rule.id),
        'name': rule.name,
        'url_pattern': rule.url_pattern,
        'throttle_type': rule.throttle_type,
        'rate': rule.rate,
    })


@extend_schema(
    summary="更新限流规则",
    tags=['API 网关'],
)
@api_view(['PUT', 'PATCH'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_update_api(request, rule_id):
    """更新限流规则"""
    try:
        rule = APILimitRule.objects.get(id=rule_id)
    except APILimitRule.DoesNotExist:
        return Response({'detail': '规则不存在'}, status=404)

    for field in ['name', 'url_pattern', 'throttle_type', 'rate', 'description']:
        val = request.data.get(field, None)
        if val is not None:
            setattr(rule, field, val)

    for field in ['is_active', 'use_regex']:
        val = request.data.get(field, None)
        if val is not None:
            setattr(rule, field, bool(val))

    if 'priority' in request.data:
        rule.priority = int(request.data['priority'])

    rule.save()

    return Response({'id': str(rule.id)})


@extend_schema(
    summary="删除限流规则",
    tags=['API 网关'],
)
@api_view(['DELETE'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_delete_api(request, rule_id):
    """删除限流规则"""
    try:
        rule = APILimitRule.objects.get(id=rule_id)
        rule.delete()
        return Response({'detail': '规则已删除'})
    except APILimitRule.DoesNotExist:
        return Response({'detail': '规则不存在'}, status=404)


@extend_schema(
    summary="切换限流规则启用状态",
    tags=['API 网关'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_toggle_api(request, rule_id):
    """切换规则启用/禁用"""
    try:
        rule = APILimitRule.objects.get(id=rule_id)
        rule.is_active = not rule.is_active
        rule.save()
        return Response({
            'id': str(rule.id),
            'is_active': rule.is_active,
        })
    except APILimitRule.DoesNotExist:
        return Response({'detail': '规则不存在'}, status=404)
