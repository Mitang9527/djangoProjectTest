"""
SaaS 后台管理系统 — DRF ViewSets。
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view
from django.utils.translation import gettext_lazy as _

from djangoProjectTest.viewsets import BaseModelViewSet
from framework.cache.view_cache import drf_cache_view, T_1_MINUTE, TAG_PERMISSIONS

from ..permissions import (
    ReadWriteTenantPermission,
    RoleViewPermission,
)
from ..mixins import TenantQuerysetMixin
from ..models import (
    Plan, PlanFeature, Tenant, TenantSubscription, TenantConfig,
    Permission, Role, TenantMember, Order, Invoice,
    GlobalConfig, FeatureFlag, ConfigHistory,
)
from ..serializers import (
    PlanSerializer, PlanFeatureSerializer, TenantSerializer,
    TenantSubscriptionSerializer, TenantConfigSerializer,
    PermissionSerializer, RoleSerializer, TenantMemberSerializer,
    OrderSerializer, InvoiceSerializer,
    GlobalConfigSerializer, FeatureFlagSerializer, ConfigHistorySerializer,
)
from ..services import PermissionService, TenantProfileService


@extend_schema_view(
    list=extend_schema(summary='List all plans', tags=['SaaS']),
    create=extend_schema(summary='Create a plan', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a plan', tags=['SaaS']),
    update=extend_schema(summary='Update a plan', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a plan', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a plan', tags=['SaaS']),
)
class PlanViewSet(BaseModelViewSet):
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.plan")]


@extend_schema_view(
    list=extend_schema(summary='List all plan features', tags=['SaaS']),
    create=extend_schema(summary='Create a plan feature', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a plan feature', tags=['SaaS']),
    update=extend_schema(summary='Update a plan feature', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a plan feature', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a plan feature', tags=['SaaS']),
)
class PlanFeatureViewSet(BaseModelViewSet):
    queryset = PlanFeature.objects.select_related('plan').all()
    serializer_class = PlanFeatureSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.plan")]


@extend_schema_view(
    list=extend_schema(summary='List all tenants', tags=['SaaS']),
    create=extend_schema(summary='Create a tenant', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a tenant', tags=['SaaS']),
    update=extend_schema(summary='Update a tenant', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a tenant', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a tenant', tags=['SaaS']),
)
class TenantViewSet(BaseModelViewSet):
    queryset = Tenant.objects.select_related('plan', 'created_by').all()
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("tenant")]

    def perform_create(self, serializer):
        super().perform_create(serializer)

    @extend_schema(
        summary='操作租户生命周期（转正式/续费/冻结/解冻/归档）',
        tags=['SaaS'],
        request={
            'application/json': {
                'type': 'object',
                'required': ['action'],
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['convert_to_formal', 'renew', 'freeze', 'unfreeze', 'archive'],
                    },
                    'service_expires_at': {'type': 'string', 'format': 'date-time', 'description': '续费到期时间（renew 必填）'},
                    'frozen_reason': {'type': 'string', 'description': '冻结原因（freeze 必填）'},
                },
            }
        },
    )
    @action(detail=True, methods=['post'], url_path='lifecycle')
    def lifecycle(self, request, pk=None):
        """对齐参考项目 POST /tenants/{id}/lifecycle。"""
        tenant = self.get_object()
        body = request.data or {}
        result = TenantProfileService.operate_lifecycle(
            tenant,
            action=body.get('action'),
            service_expires_at=body.get('service_expires_at'),
            frozen_reason=body.get('frozen_reason'),
        )
        if 'error' in result:
            return Response({"detail": result["error"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @extend_schema(
        summary='租户用量统计（成员数/资产数/存储 vs 套餐配额）',
        tags=['SaaS'],
    )
    @action(detail=True, methods=['get'], url_path='usage')
    def usage(self, request, pk=None):
        """对齐参考项目 GET /tenants/{id}/usage。"""
        tenant = self.get_object()
        return Response(TenantProfileService.get_usage(tenant))


@extend_schema_view(
    list=extend_schema(summary='List all tenant subscriptions', tags=['SaaS']),
    create=extend_schema(summary='Create a tenant subscription', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a tenant subscription', tags=['SaaS']),
    update=extend_schema(summary='Update a tenant subscription', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a tenant subscription', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a tenant subscription', tags=['SaaS']),
)
class TenantSubscriptionViewSet(TenantQuerysetMixin, BaseModelViewSet):
    queryset = TenantSubscription.objects.select_related('tenant', 'plan').all()
    serializer_class = TenantSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.subscription")]


@extend_schema_view(
    list=extend_schema(summary='List all tenant configs', tags=['SaaS']),
    create=extend_schema(summary='Create a tenant config', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a tenant config', tags=['SaaS']),
    update=extend_schema(summary='Update a tenant config', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a tenant config', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a tenant config', tags=['SaaS']),
)
class TenantConfigViewSet(TenantQuerysetMixin, BaseModelViewSet):
    queryset = TenantConfig.objects.select_related('tenant').all()
    serializer_class = TenantConfigSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("config")]


@extend_schema_view(
    list=extend_schema(summary='List all permissions', tags=['SaaS']),
    create=extend_schema(summary='Create a permission', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a permission', tags=['SaaS']),
    update=extend_schema(summary='Update a permission', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a permission', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a permission', tags=['SaaS']),
)
class PermissionViewSet(BaseModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("role")]


@extend_schema(
    summary="获取按模块分组的权限列表",
    tags=["SaaS"],
    responses={200: {"type": "object", "properties": {
        "modules": {"type": "array", "items": {
            "type": "object", "properties": {
                "module": {"type": "string"},
                "module_name": {"type": "string"},
                "permissions": {"type": "array", "items": {"type": "object"}},
            }
        }},
    }}},
)
@api_view(["GET"])
@drf_permission_classes([permissions.IsAuthenticated, RoleViewPermission])
def permissions_grouped(request):
    """返回按模块分组的权限树结构，用于角色权限分配界面。"""
    module_names = {
        'system': _('系统管理'),
        'tenant': _('租户管理'),
        'user': _('用户管理'),
        'billing': _('计费管理'),
        'analytics': _('数据分析'),
    }

    permissions_qs = Permission.objects.filter(is_active=True).order_by('module', 'slug')

    modules_dict = {}
    for perm in permissions_qs:
        module = perm.module
        if module not in modules_dict:
            modules_dict[module] = {
                'module': module,
                'module_name': module_names.get(module, module),
                'permissions': []
            }
        modules_dict[module]['permissions'].append({
            'id': str(perm.id),
            'name': perm.name,
            'slug': perm.slug,
            'description': perm.description,
        })

    modules_list = list(modules_dict.values())
    modules_list.sort(key=lambda x: x['module'])

    return Response({
        'modules': modules_list,
    })


@extend_schema_view(
    list=extend_schema(summary='List all roles', tags=['SaaS']),
    create=extend_schema(summary='Create a role', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a role', tags=['SaaS']),
    update=extend_schema(summary='Update a role', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a role', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a role', tags=['SaaS']),
)
class RoleViewSet(TenantQuerysetMixin, BaseModelViewSet):
    queryset = Role.objects.prefetch_related('permissions').all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("role")]
    filterset_fields = ['tenant', 'is_active']


@extend_schema_view(
    list=extend_schema(summary='List all tenant members', tags=['SaaS']),
    create=extend_schema(summary='Create a tenant member', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a tenant member', tags=['SaaS']),
    update=extend_schema(summary='Update a tenant member', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a tenant member', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a tenant member', tags=['SaaS']),
)
class TenantMemberViewSet(TenantQuerysetMixin, BaseModelViewSet):
    queryset = TenantMember.objects.select_related('user', 'tenant', 'role', 'invited_by').all()
    serializer_class = TenantMemberSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("user")]


@extend_schema_view(
    list=extend_schema(summary='List all orders', tags=['SaaS']),
    create=extend_schema(summary='Create an order', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve an order', tags=['SaaS']),
    update=extend_schema(summary='Update an order', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update an order', tags=['SaaS']),
    destroy=extend_schema(summary='Delete an order', tags=['SaaS']),
)
class OrderViewSet(TenantQuerysetMixin, BaseModelViewSet):
    queryset = Order.objects.select_related('tenant', 'user', 'plan').all()
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.order")]


@extend_schema_view(
    list=extend_schema(summary='List all invoices', tags=['SaaS']),
    create=extend_schema(summary='Create a invoice', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a invoice', tags=['SaaS']),
    update=extend_schema(summary='Update a invoice', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a invoice', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a invoice', tags=['SaaS']),
)
class InvoiceViewSet(TenantQuerysetMixin, BaseModelViewSet):
    queryset = Invoice.objects.select_related('order', 'tenant').all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.invoice")]


# ============================================================
# 配置中心 ViewSet
# ============================================================

@extend_schema_view(
    list=extend_schema(summary='List all global configs', tags=['Config Center']),
    create=extend_schema(summary='Create a global config', tags=['Config Center']),
    retrieve=extend_schema(summary='Retrieve a global config', tags=['Config Center']),
    update=extend_schema(summary='Update a global config', tags=['Config Center']),
    partial_update=extend_schema(summary='Partially update a global config', tags=['Config Center']),
    destroy=extend_schema(summary='Delete a global config', tags=['Config Center']),
)
class GlobalConfigViewSet(BaseModelViewSet):
    queryset = GlobalConfig.objects.select_related('created_by', 'updated_by').all()
    serializer_class = GlobalConfigSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['category', 'is_active', 'is_public']
    search_fields = ['key', 'name', 'description']
    ordering_fields = ['key', 'category', 'created_at', 'updated_at']
    ordering = ['-created_at']


@extend_schema_view(
    list=extend_schema(summary='List all feature flags', tags=['Feature Flag']),
    create=extend_schema(summary='Create a feature flag', tags=['Feature Flag']),
    retrieve=extend_schema(summary='Retrieve a feature flag', tags=['Feature Flag']),
    update=extend_schema(summary='Update a feature flag', tags=['Feature Flag']),
    partial_update=extend_schema(summary='Partially update a feature flag', tags=['Feature Flag']),
    destroy=extend_schema(summary='Delete a feature flag', tags=['Feature Flag']),
)
class FeatureFlagViewSet(BaseModelViewSet):
    queryset = FeatureFlag.objects.select_related('created_by', 'updated_by').all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['status', 'rollout_strategy']
    search_fields = ['key', 'name', 'description']
    ordering_fields = ['key', 'status', 'created_at', 'updated_at']
    ordering = ['-created_at']


@extend_schema_view(
    list=extend_schema(summary='List config history', tags=['Config Center']),
    retrieve=extend_schema(summary='Retrieve config history', tags=['Config Center']),
)
class ConfigHistoryViewSet(BaseModelViewSet):
    queryset = ConfigHistory.objects.select_related('operator').all()
    serializer_class = ConfigHistorySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['config_key', 'config_type', 'operation']
    search_fields = ['config_key']
    ordering_fields = ['-created_at']
    ordering = ['-created_at']
    http_method_names = ['get', 'head', 'options']  # 只读


# ---------------------------------------------------------------------------
# /api/saas/me/permissions/ — 返回当前用户拥有的权限 slug 集合
# ---------------------------------------------------------------------------
@extend_schema(
    summary="获取当前用户权限列表",
    tags=["SaaS"],
    responses={200: {"type": "object", "properties": {
        "is_super_admin": {"type": "boolean"},
        "permissions": {"type": "array", "items": {"type": "string"}},
    }}},
)
@api_view(["GET"])
@drf_permission_classes([permissions.IsAuthenticated])
@drf_cache_view("me_perms", timeout=T_1_MINUTE, tags=[TAG_PERMISSIONS])
def me_permissions(request):
    """返回当前登录用户在当前租户下拥有的权限 slug 集合。"""
    tenant_id = getattr(request, 'tenant_id', None) or request.session.get('current_tenant_id')
    result = PermissionService.get_user_permissions(request.user, tenant_id)
    return Response(result)
