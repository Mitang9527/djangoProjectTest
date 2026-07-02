"""
SaaS 后台管理系统 - 视图函数
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View
from rest_framework import viewsets, permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view
from loguru import logger

# 视图缓存
from utils.cache.view_cache import (
    drf_cache_view, cache_view,
    T_30_SECONDS, T_1_MINUTE, T_5_MINUTES,
    TAG_DASHBOARD, TAG_PERMISSIONS, TAG_TENANT, TAG_EXPORT,
)

from .permissions import (
    TenantViewPermission, TenantManagePermission,
    UserViewPermission, UserManagePermission,
    RoleViewPermission, RoleManagePermission,
    SystemViewPermission, SystemManagePermission,
    PlanViewPermission, PlanManagePermission,
    OrderViewPermission, OrderManagePermission,
    InvoiceViewPermission, InvoiceManagePermission,
    AdbViewPermission, AdbOperatePermission,
    ConfigViewPermission, ConfigManagePermission,
    SystemDashboardPermission,
    SystemLogsViewPermission,
    SystemSettingsBasicPermission,
    SystemSettingsBackupPermission,
    ReadWriteTenantPermission,
    HasTenantPermission,
)
from .mixins import TenantQuerysetMixin

from .models import (
    Plan,
    PlanFeature,
    Tenant,
    TenantSubscription,
    TenantConfig,
    Permission,
    Role,
    TenantMember,
    Order,
    Invoice
)
from .serializers import (
    PlanSerializer,
    PlanFeatureSerializer,
    TenantSerializer,
    TenantSubscriptionSerializer,
    TenantConfigSerializer,
    PermissionSerializer,
    RoleSerializer,
    TenantMemberSerializer,
    OrderSerializer,
    InvoiceSerializer
)

THEME_OPTIONS = [
    ('light', _('白天模式')),
    ('dark', _('夜晚模式')),
    ('system', _('跟随系统')),
]


@method_decorator(login_required, name='dispatch')
class DashboardView(View):
    template_name = 'saas/dashboard.html'

    def get(self, request, *args, **kwargs):
        from .permissions import _is_super_admin
        # 获取基础数据用于展示
        tenants = Tenant.objects.count()
        active_orders = Order.objects.filter(status='paid').count()
        users = TenantMember.objects.filter(is_active=True).count()
        recent_orders = Order.objects.order_by('-created_at')[:10]

        context = {
            'title': _('仪表盘'),
            'tenants': tenants,
            'active_orders': active_orders,
            'users': users,
            'recent_orders': recent_orders,
            'is_super_admin': _is_super_admin(request.user),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name='dispatch')
class PlaceholderModuleView(View):
    template_name = 'saas/saas_list.html'
    page_title = ''
    page_description = _('该模块的详细管理功能正在建设中，目前您可以看到此占位页面。')
    action_text = _('新增')

    def get_context_data(self, request=None):
        from .permissions import _is_super_admin
        context = {
            'title': self.page_title,
            'description': self.page_description,
            'action_text': self.action_text,
        }
        if request:
            context['is_super_admin'] = _is_super_admin(request.user)
        return context

    def get(self, request):
        return render(request, self.template_name, self.get_context_data(request))


@method_decorator(login_required, name='dispatch')
class TenantListView(View):
    template_name = 'saas/tenant_list.html'

    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, self.template_name, {
            'title': _('租户管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class MemberListView(View):
    template_name = 'saas/member_list.html'

    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, self.template_name, {
            'title': _('用户管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class RoleListView(View):
    template_name = 'saas/role_list.html'

    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, self.template_name, {
            'title': _('角色管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class PermissionListView(View):
    template_name = 'saas/permission_list.html'

    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, self.template_name, {
            'title': _('权限管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


class PlanListView(PlaceholderModuleView):
    page_title = _('套餐管理')
    page_description = _('这里将用于维护套餐、功能包和价格策略，当前先提供 SaaS 内部占位页面。')
    action_text = _('新增套餐')


class SubscriptionListView(PlaceholderModuleView):
    page_title = _('订阅管理')
    page_description = _('这里将用于查看租户订阅周期、续费情况和套餐生效状态，后续补充业务明细。')
    action_text = _('新增订阅')


class OrderListView(PlaceholderModuleView):
    page_title = _('订单管理')
    page_description = _('这里将用于维护订单记录、支付状态和业务流水，当前先提供独立的管理页面。')
    action_text = _('新增订单')


class InvoiceListView(PlaceholderModuleView):
    page_title = _('发票管理')
    page_description = _('这里将用于管理发票申请、开票状态和发票归档，详细流程后续再实现。')
    action_text = _('新增发票')


@method_decorator(login_required, name='dispatch')
class ConfigListView(View):
    template_name = 'saas/system_settings.html'

    def get_supported_languages(self):
        return list(getattr(settings, 'LANGUAGES', [('zh-hans', _('简体中文')), ('en', _('English'))]))

    def get_current_language(self, request):
        current_language = getattr(request, 'LANGUAGE_CODE', None) or request.COOKIES.get(
            settings.LANGUAGE_COOKIE_NAME,
            settings.LANGUAGE_CODE,
        )
        supported_languages = {code for code, _ in self.get_supported_languages()}
        return current_language if current_language in supported_languages else settings.LANGUAGE_CODE

    def get_current_theme(self, request):
        theme = request.COOKIES.get('theme', 'light')
        return theme if theme in dict(THEME_OPTIONS) else 'light'

    def get_context_data(self, request):
        from .permissions import _is_super_admin
        return {
            'title': _('系统设置'),
            'available_languages': self.get_supported_languages(),
            'theme_options': THEME_OPTIONS,
            'current_language': self.get_current_language(request),
            'current_theme': self.get_current_theme(request),
            'is_super_admin': _is_super_admin(request.user),
        }

    def get(self, request):
        return render(request, self.template_name, self.get_context_data(request))

    def post(self, request):
        supported_languages = {code for code, _ in self.get_supported_languages()}
        submitted_language = request.POST.get('language', self.get_current_language(request))
        submitted_theme = request.POST.get('theme', self.get_current_theme(request))

        language = submitted_language if submitted_language in supported_languages else settings.LANGUAGE_CODE
        theme = submitted_theme if submitted_theme in dict(THEME_OPTIONS) else 'light'

        if submitted_language not in supported_languages:
            messages.warning(request, _('所选语言暂不支持，已恢复为默认语言。'))

        if submitted_theme not in dict(THEME_OPTIONS):
            messages.warning(request, _('所选主题无效，已恢复为默认主题。'))

        translation.activate(language)

        response = redirect('saas:config-page')
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            language,
            max_age=60 * 60 * 24 * 365,
            samesite='Lax',
        )
        response.set_cookie(
            'theme',
            theme,
            max_age=60 * 60 * 24 * 365,
            samesite='Lax',
        )
        messages.success(request, _('系统设置已保存。'))
        return response


@extend_schema_view(
    list=extend_schema(summary='List all plans', tags=['SaaS']),
    create=extend_schema(summary='Create a plan', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a plan', tags=['SaaS']),
    update=extend_schema(summary='Update a plan', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a plan', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a plan', tags=['SaaS']),
)
class PlanViewSet(viewsets.ModelViewSet):
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
class PlanFeatureViewSet(viewsets.ModelViewSet):
    queryset = PlanFeature.objects.all()
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
class TenantViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.all()
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("tenant")]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema_view(
    list=extend_schema(summary='List all tenant subscriptions', tags=['SaaS']),
    create=extend_schema(summary='Create a tenant subscription', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve a tenant subscription', tags=['SaaS']),
    update=extend_schema(summary='Update a tenant subscription', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update a tenant subscription', tags=['SaaS']),
    destroy=extend_schema(summary='Delete a tenant subscription', tags=['SaaS']),
)
class TenantSubscriptionViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = TenantSubscription.objects.all()
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
class TenantConfigViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = TenantConfig.objects.all()
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
class PermissionViewSet(viewsets.ModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("role")]


# ---------------------------------------------------------------------------
# /api/saas/permissions/grouped/ — 返回按模块分组的权限树
# ---------------------------------------------------------------------------
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
    """
    返回按模块分组的权限树结构，用于角色权限分配界面。
    """
    from django.utils.translation import gettext_lazy as _

    module_names = {
        'system': _('系统管理'),
        'tenant': _('租户管理'),
        'user': _('用户管理'),
        'billing': _('计费管理'),
        'analytics': _('数据分析'),
    }

    # 获取所有启用的权限
    permissions = Permission.objects.filter(is_active=True).order_by('module', 'slug')

    # 按模块分组
    modules_dict = {}
    for perm in permissions:
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

    # 转换为有序列表
    modules_list = list(modules_dict.values())
    # 按模块名称排序
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
class RoleViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
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
class TenantMemberViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = TenantMember.objects.all()
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
class OrderViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.order")]


@extend_schema_view(
    list=extend_schema(summary='List all invoices', tags=['SaaS']),
    create=extend_schema(summary='Create an invoice', tags=['SaaS']),
    retrieve=extend_schema(summary='Retrieve an invoice', tags=['SaaS']),
    update=extend_schema(summary='Update an invoice', tags=['SaaS']),
    partial_update=extend_schema(summary='Partially update an invoice', tags=['SaaS']),
    destroy=extend_schema(summary='Delete an invoice', tags=['SaaS']),
)
class InvoiceViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, ReadWriteTenantPermission.for_module("billing.invoice")]


# ---------------------------------------------------------------------------
# /api/saas/me/permissions/ — 返回当前用户拥有的权限 slug 集合
# 前端用来控制菜单项是否显示
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
    """
    返回当前登录用户在当前租户下拥有的权限 slug 集合。
    超级管理员返回全部权限 slug。
    前端可缓存此结果用于菜单渲染。
    """
    from .permissions import _is_super_admin
    from .permission_registry import ALL_PERMISSION_SLUGS

    user = request.user

    if _is_super_admin(user):
        return Response({
            "is_super_admin": True,
            "permissions": ALL_PERMISSION_SLUGS,
        })

    # 按当前租户过滤成员关系
    tenant_id = getattr(request, 'tenant_id', None) or request.session.get('current_tenant_id')
    members = (
        TenantMember.objects
        .filter(user=user, is_active=True)
        .select_related("role")
        .prefetch_related("role__permissions")
    )
    if tenant_id:
        members = members.filter(tenant_id=tenant_id)

    slugs = set()
    for member in members:
        role = member.role
        if not role or not role.is_active:
            continue
        for perm in role.permissions.filter(is_active=True):
            slugs.add(perm.slug)

    # 3) 用户直接关联的系统角色（role）
    user_role = getattr(user, 'role', None)
    if user_role and user_role.is_active:
        for perm in user_role.permissions.filter(is_active=True):
            slugs.add(perm.slug)

    return Response({
        "is_super_admin": False,
        "permissions": sorted(slugs),
    })


# ===============================================
# 系统用户管理页面视图
# ===============================================
class SystemUserListView(View):
    """系统用户管理页面 — 展示用户列表及其租户角色关系"""

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        from .permissions import _is_super_admin
        is_super = _is_super_admin(request.user)

        context = {
            'title': _('系统用户'),
            'current_tenant_id': str(tenant.id) if tenant else '',
            'current_tenant_name': tenant.name if tenant else _('全部租户'),
            'all_tenants_json': '[]',
            'tenant_roles_json': '[]',
            'is_super_admin': is_super,
        }

        if is_super:
            context['all_tenants_json'] = json.dumps([
                {'id': str(t['id']), 'name': t['name'], 'slug': t['slug']}
                for t in Tenant.objects.filter(status='active').values('id', 'name', 'slug')
            ])

        if tenant:
            context['tenant_roles_json'] = json.dumps([
                {'id': str(r['id']), 'name': r['name'], 'slug': r['slug']}
                for r in Role.objects.filter(tenant=tenant, is_active=True).values('id', 'name', 'slug')
            ])

        return render(request, 'saas/user_list.html', context)


# ===============================================
# 租户切换 API
# ===============================================

@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated])
@drf_cache_view("me_tenants", timeout=T_1_MINUTE, tags=[TAG_TENANT])
def me_tenants(request):
    """返回当前用户可访问的租户列表"""
    from .permissions import _is_super_admin
    is_super = _is_super_admin(request.user)
    if is_super:
        tenants = list(Tenant.objects.filter(status='active').values('id', 'name', 'slug'))
    else:
        members = TenantMember.objects.filter(
            user=request.user, is_active=True
        ).select_related('tenant')
        tenants = [
            {'id': str(m.tenant.id), 'name': m.tenant.name, 'slug': m.tenant.slug}
            for m in members if m.tenant.status == 'active'
        ]

    current_id = request.session.get('current_tenant_id')
    return Response({
        'tenants': tenants,
        'current_tenant_id': current_id,
    })


@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated])
def switch_tenant(request):
    """切换当前活跃租户（传 null 清除上下文，回到管理员全量视图）"""
    tenant_id = request.data.get('tenant_id')
    
    if not tenant_id:
        request.session.pop('current_tenant_id', None)
        logger.info(f"用户 {request.user.username} 清除租户上下文，进入全局视图")
        return Response({'msg': '已切换到全局视图', 'tenant': None})

    is_super = request.user.is_superuser or getattr(request.user, 'role', 'user') == 'admin'
    if is_super:
        tenant = Tenant.objects.filter(id=tenant_id).first()
    else:
        member = TenantMember.objects.filter(
            user=request.user, tenant_id=tenant_id, is_active=True
        ).select_related('tenant').first()
        tenant = member.tenant if member else None

    if not tenant:
        return Response({'msg': '无权限访问该租户'}, status=403)

    request.session['current_tenant_id'] = str(tenant.id)
    logger.info(f"用户 {request.user.username} 切换到租户 {tenant.name}")

    return Response({
        'msg': f'已切换到 {tenant.name}',
        'tenant': {'id': str(tenant.id), 'name': tenant.name, 'slug': tenant.slug},
    })


# ===============================================
# 系统仪表盘
# ===============================================

@method_decorator(login_required, name='dispatch')
class SystemDashboardView(View):
    """系统仪表盘 — 需要 system.dashboard 权限"""
    template_name = 'saas/system_dashboard.html'

    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, self.template_name, {
            'title': _('系统仪表盘'),
            'is_super_admin': _is_super_admin(request.user),
        })


@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
@drf_cache_view("sys_dashboard", timeout=T_30_SECONDS, tags=[TAG_DASHBOARD])
def system_dashboard_api(request):
    """返回系统仪表盘统计数据"""
    total_tenants = Tenant.objects.count()
    active_tenants = Tenant.objects.filter(status='active').count()
    total_users = TenantMember.objects.filter(is_active=True).count()
    total_roles = Role.objects.filter(is_active=True).count()
    total_orders = Order.objects.count()
    revenue = Order.objects.filter(status='paid').aggregate(
        total=Sum('amount')
    )['total'] or 0
    recent_orders = list(Order.objects.order_by('-created_at')[:5].values(
        'id', 'order_no', 'amount', 'status', 'created_at'
    ))

    # 租户用户数排行
    top_tenants = list(Tenant.objects.filter(status='active').annotate(
        member_count=Count('members', filter=Q(members__is_active=True))
    ).order_by('-member_count')[:5].values('id', 'name', 'member_count'))

    # 最近 30 天新增用户趋势
    thirty_days_ago = datetime.now() - timedelta(days=30)
    daily_new_users = list(
        TenantMember.objects.filter(created_at__gte=thirty_days_ago)
        .extra(select={'day': "date(created_at)"})
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    return Response({
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'total_users': total_users,
        'total_roles': total_roles,
        'total_orders': total_orders,
        'revenue': float(revenue),
        'recent_orders': recent_orders,
        'top_tenants': top_tenants,
        'daily_new_users': [
            {'day': str(d['day']), 'count': d['count']}
            for d in daily_new_users
        ],
    })


# ===============================================
# 系统日志
# ===============================================

LOG_DIR = Path(settings.BASE_DIR) / 'logs'
LOG_LEVELS = ['TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

# 日志行正则：2026-07-02 10:21:05 | LEVEL    | ...
LOG_LINE_RE = re.compile(
    r'^(?P<datetime>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*'
    r'(?P<level>TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|'
)


def _parse_log_file(filepath: Path, level_filter=None, search=None,
                    date_from=None, date_to=None, page=1, page_size=50):
    """解析 .log 文件，返回分页结果"""
    entries = []
    if not filepath.exists():
        return {'entries': [], 'total': 0, 'page': page, 'page_size': page_size}

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        m = LOG_LINE_RE.match(line)
        if m:
            ts = m.group('datetime')
            level = m.group('level')

            # 收集后续多行内容直到下一条日志
            body_lines = [line[m.end():].strip()]
            i += 1
            while i < len(lines):
                next_m = LOG_LINE_RE.match(lines[i])
                if next_m:
                    break
                body_lines.append(lines[i].rstrip('\n'))
                i += 1

            # 过滤
            if level_filter and level not in level_filter:
                continue
            if date_from and ts < date_from:
                continue
            if date_to and ts > date_to:
                continue
            if search:
                body = ' '.join(body_lines)
                if search.lower() not in body.lower():
                    continue

            entries.append({
                'datetime': ts,
                'level': level,
                'message': '\n'.join(body_lines)[:2000],
            })
        else:
            i += 1

    total = len(entries)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        'entries': entries[start:end],
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, (total + page_size - 1) // page_size),
    }


@method_decorator(login_required, name='dispatch')
class SystemLogsView(View):
    """系统日志页 — 需要 system.logs.view 权限"""
    template_name = 'saas/system_logs.html'

    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, self.template_name, {
            'title': _('系统日志'),
            'is_super_admin': _is_super_admin(request.user),
            'log_levels': LOG_LEVELS,
        })


@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemLogsViewPermission])
def system_logs_api(request):
    """返回日志数据，支持分页和筛选"""
    level = request.query_params.get('level', '').upper()
    search = request.query_params.get('search', '')
    date_from = request.query_params.get('date_from', '')
    date_to = request.query_params.get('date_to', '')
    page = int(request.query_params.get('page', 1))
    page_size = min(int(request.query_params.get('page_size', 50)), 200)

    level_filter = [l for l in level.split(',') if l in LOG_LEVELS] if level else None

    # 找最新的日志文件
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_log = LOG_DIR / f'{today_str}.log'
    if today_log.exists():
        log_file = today_log
    else:
        log_files = sorted(LOG_DIR.glob('*.log'), reverse=True)
        log_file = log_files[0] if log_files else None

    if not log_file:
        return Response({'entries': [], 'total': 0, 'page': 1, 'page_size': page_size, 'total_pages': 1})

    result = _parse_log_file(
        log_file, level_filter=level_filter, search=search,
        date_from=date_from, date_to=date_to, page=page, page_size=page_size
    )
    result['log_file'] = str(log_file.name)
    return Response(result)


# ===============================================
# 系统设置（基本 / 安全 / 通知 / 集成 / 备份）
# ===============================================

SETTINGS_CATEGORIES = {
    'basic': {
        'title': _('基本设置'),
        'icon': 'settings',
        'permission': 'system.settings.basic',
        'category': 'general',
    },
    'security': {
        'title': _('安全设置'),
        'icon': 'shield',
        'permission': 'system.settings.security',
        'category': 'security',
    },
    'notification': {
        'title': _('通知设置'),
        'icon': 'bell',
        'permission': 'system.settings.notification',
        'category': 'general',
    },
    'integration': {
        'title': _('集成设置'),
        'icon': 'link',
        'permission': 'system.settings.integration',
        'category': 'integration',
    },
    'backup': {
        'title': _('备份恢复'),
        'icon': 'archive',
        'permission': 'system.settings.backup',
        'category': 'general',
    },
}


@method_decorator(login_required, name='dispatch')
class SystemSettingsView(View):
    """系统设置页 — 需要 system.settings.view 权限；子页各自检查"""
    template_name = 'saas/system_settings_v2.html'

    def get(self, request):
        from .permissions import _is_super_admin
        tenant = getattr(request, 'tenant', None)
        is_super = _is_super_admin(request.user)

        # 检查哪些设置页用户有权限
        accessible = {}
        for key, cat in SETTINGS_CATEGORIES.items():
            accessible[key] = is_super or HasTenantPermission._user_has_slug(
                request.user, cat['permission']
            )

        # 获取现有配置值（用于预填表单）
        configs = {}
        if tenant:
            for c in TenantConfig.objects.filter(tenant=tenant).values('key', 'value', 'category'):
                configs[c['key']] = c

        return render(request, self.template_name, {
            'title': _('系统设置'),
            'is_super_admin': is_super,
            'settings_categories': SETTINGS_CATEGORIES,
            'accessible': accessible,
            'existing_configs': json.dumps(configs),
            'current_tenant_id': str(tenant.id) if tenant else '',
        })


@api_view(['GET', 'POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemSettingsBasicPermission])
def system_settings_config_api(request):
    """读取/保存系统设置配置项"""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return Response({'error': _('请先选择租户上下文')}, status=400)

    if request.method == 'GET':
        category = request.query_params.get('category', 'general')
        configs = TenantConfig.objects.filter(tenant=tenant, category=category)
        return Response({
            'configs': {
                c.key: c.value for c in configs
            }
        })

    # POST: 保存配置
    data = request.data.get('configs', {})
    category = request.data.get('category', 'general')
    updated = []
    for key, value in data.items():
        config, created = TenantConfig.objects.update_or_create(
            tenant=tenant,
            key=key,
            defaults={
                'value': str(value),
                'category': category,
                'description': f'{category} settings',
            }
        )
        updated.append({'key': key, 'value': value, 'created': created})

    logger.info(f"租户 {tenant.name} 更新了 {category} 设置")
    return Response({'updated': updated, 'status': 'ok'})


# ===============================================
# 备份/恢复 API
# ===============================================

@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemSettingsBackupPermission])
def system_backup_api(request):
    """触发系统数据备份（需要 system.settings.backup 权限）"""
    import subprocess
    import sys

    backup_dir = Path(settings.BASE_DIR) / 'backups'
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'backup_{timestamp}.json'

    try:
        result = subprocess.run(
            [sys.executable, 'manage.py', 'dumpdata',
             'saas', 'users', '--indent', '2',
             '--output', str(backup_dir / filename)],
            capture_output=True, text=True, timeout=300,
            cwd=str(settings.BASE_DIR)
        )
        if result.returncode == 0:
            logger.info(f"系统备份成功: {filename}")
            return Response({'status': 'ok', 'filename': filename, 'msg': _('备份成功')})
        else:
            logger.error(f"系统备份失败: {result.stderr}")
            return Response({'status': 'error', 'msg': result.stderr[:500]}, status=500)
    except subprocess.TimeoutExpired:
        return Response({'status': 'error', 'msg': _('备份超时')}, status=500)
    except Exception as e:
        return Response({'status': 'error', 'msg': str(e)}, status=500)


@extend_schema(exclude=True)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemSettingsBackupPermission])
def system_backup_list_api(request):
    """列出备份文件列表"""
    backup_dir = Path(settings.BASE_DIR) / 'backups'
    if not backup_dir.exists():
        return Response({'backups': []})

    backups = []
    for f in sorted(backup_dir.glob('*.json'), reverse=True):
        stat = f.stat()
        backups.append({
            'filename': f.name,
            'size': stat.st_size,
            'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    return Response({'backups': backups})


# ===============================================
# 数据导出 API
# ===============================================
@extend_schema(
    summary="导出数据",
    description="按模型、格式、字段导出数据。支持 xlsx/csv/pdf 格式。",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'model': {'type': 'string', 'description': '模型标识如 saas.Tenant'},
                'format': {'type': 'string', 'description': 'xlsx / csv / pdf'},
                'fields': {'type': 'array', 'items': {'type': 'string'}, 'description': '导出字段（可选，不传使用默认）'},
                'filters': {'type': 'object', 'description': '额外筛选条件（可选）'},
                'async': {'type': 'boolean', 'description': '是否异步导出（>1万条建议开启）'},
            },
            'required': ['model', 'format'],
        }
    },
    tags=['数据导出'],
    responses={200: {'content': {'application/octet-stream': {}}}},
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def export_data(request):
    """
    导出数据为 Excel / CSV / PDF。
    小数据量直接返回文件流；大数据量进入 Celery 异步任务。
    """
    from utils.export import get_exporter, ExportConfig, EXPORTABLE_MODELS

    model_label = request.data.get('model', '')
    fmt = request.data.get('format', 'xlsx')
    fields = request.data.get('fields')
    filters = request.data.get('filters', {})
    filename = request.data.get('filename')
    use_async = request.data.get('async', False)

    # 验证
    if model_label not in EXPORTABLE_MODELS:
        return Response({
            'error': f'不支持的导出模型: {model_label}',
            'available': list(EXPORTABLE_MODELS.keys()),
        }, status=400)

    base = EXPORTABLE_MODELS[model_label]

    try:
        config = ExportConfig(
            model_label=model_label,
            fields=fields or base.fields,
            headers=base.headers,
            filename=filename or base.filename,
            filters={**base.filters, **filters},
            related_select=base.related_select,
            related_prefetch=base.related_prefetch,
            order_by=base.order_by,
        )
        exporter = get_exporter(config, fmt)
    except ValueError as e:
        return Response({'error': str(e)}, status=400)

    qs = exporter.get_queryset()

    # 超过 1 万条自动走异步
    if use_async or qs.count() > 10000:
        from .tasks import async_export_data
        task = async_export_data.delay(
            model_label=model_label,
            fmt=fmt,
            fields=fields,
            filters=filters,
            filename=filename,
        )
        return Response({
            'status': 'processing',
            'task_id': task.id,
            'msg': '数据量较大，已转为后台异步导出，完成后可下载',
        })

    # 同步导出
    data = exporter.export(qs)
    response = HttpResponse(data, content_type=exporter.content_type)
    response['Content-Disposition'] = (
        f'attachment; filename="{config.filename}.{exporter.extension}"'
    )
    return response


@extend_schema(
    summary="获取可导出模型列表",
    description="返回所有可导出模型的标识和可用字段",
    tags=['数据导出'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
@drf_cache_view("export_models", timeout=T_5_MINUTES, tags=[TAG_EXPORT])
def export_models(request):
    """列出所有可导出模型及其字段"""
    from utils.export import EXPORTABLE_MODELS
    models = {}
    for label, cfg in EXPORTABLE_MODELS.items():
        models[label] = {
            'name': cfg.filename,
            'fields': cfg.fields,
            'headers': cfg.headers,
            'supported_formats': ['xlsx', 'csv', 'pdf'],
        }
    return Response({'models': models})


# ═══════════════════════════════════════════════════════════════
# API 网关管理视图
# ═══════════════════════════════════════════════════════════════

class GatewayDashboardView(View):
    """API 网关仪表盘"""

    @method_decorator(login_required)
    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, 'saas/gateway_dashboard.html', {
            'title': 'API 网关',
            'is_super_admin': _is_super_admin(request.user),
        })


class GatewayRulesView(View):
    """限流规则管理页面"""

    @method_decorator(login_required)
    def get(self, request):
        from .permissions import _is_super_admin
        return render(request, 'saas/gateway_rules.html', {
            'title': '限流规则管理',
            'is_super_admin': _is_super_admin(request.user),
        })


# ── 网关 API ────────────────────────────────────────────

@extend_schema(
    summary="获取网关概览统计数据",
    description="返回当前限流规则数量、活跃规则数、最近拦截统计",
    tags=['API 网关'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_dashboard_api(request):
    """网关仪表盘数据"""
    from .models import APILimitRule
    from django.db.models import Count

    rules = APILimitRule.objects.all()
    active_count = rules.filter(is_active=True).count()

    # 按类型统计
    type_stats = {}
    for rt in APILimitRule.RuleType:
        type_stats[rt.value] = rules.filter(is_active=True, throttle_type=rt.value).count()

    # 全局默认值
    from utils.gateway.throttle import DEFAULT_THROTTLE_RATES

    return Response({
        'total_rules': rules.count(),
        'active_rules': active_count,
        'inactive_rules': rules.count() - active_count,
        'type_stats': type_stats,
        'global_defaults': DEFAULT_THROTTLE_RATES,
        'throttle_types': [
            {'id': 'ip', 'name': 'IP 限流', 'desc': '按客户端 IP 地址限制'},
            {'id': 'user', 'name': '用户限流', 'desc': '按认证用户限制'},
            {'id': 'tenant', 'name': '租户限流', 'desc': '按租户限制'},
            {'id': 'endpoint', 'name': '端点限流', 'desc': '按 API 路由限制'},
        ],
    })


@extend_schema(
    summary="列出所有限流规则",
    tags=['API 网关'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rules_list_api(request):
    """列出所有限流规则"""
    from .models import APILimitRule
    rules = APILimitRule.objects.all().order_by('priority', '-created_at')
    data = []
    for r in rules:
        data.append({
            'id': str(r.id),
            'name': r.name,
            'url_pattern': r.url_pattern,
            'throttle_type': r.throttle_type,
            'throttle_type_display': r.get_throttle_type_display(),
            'rate': r.rate,
            'is_active': r.is_active,
            'use_regex': r.use_regex,
            'priority': r.priority,
            'description': r.description,
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': r.updated_at.strftime('%Y-%m-%d %H:%M'),
        })
    return Response({'rules': data})


@extend_schema(
    summary="创建限流规则",
    tags=['API 网关'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_create_api(request):
    """创建新的限流规则"""
    from .models import APILimitRule

    name = request.data.get('name', '').strip()
    url_pattern = request.data.get('url_pattern', '').strip()
    throttle_type = request.data.get('throttle_type', 'ip')
    rate = request.data.get('rate', '100/h')
    is_active = request.data.get('is_active', True)
    use_regex = request.data.get('use_regex', False)
    priority = request.data.get('priority', 0)
    description = request.data.get('description', '')

    if not name:
        return Response({'code': 400, 'msg': '规则名称不能为空'}, status=400)
    if not url_pattern:
        return Response({'code': 400, 'msg': 'URL 模式不能为空'}, status=400)

    # 验证 throttle_type
    valid_types = [t[0] for t in APILimitRule.RuleType.choices]
    if throttle_type not in valid_types:
        return Response({'code': 400, 'msg': f'无效的限流类型，可选: {", ".join(valid_types)}'}, status=400)

    # 验证 rate 格式
    import re as _re
    if not _re.match(r'^\d+/(s|m|h|d)$', rate):
        return Response({'code': 400, 'msg': '速率格式无效，示例: 100/h'}, status=400)

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
        'code': 200,
        'msg': '规则创建成功',
        'data': {
            'id': str(rule.id),
            'name': rule.name,
            'url_pattern': rule.url_pattern,
            'throttle_type': rule.throttle_type,
            'rate': rule.rate,
        },
    })


@extend_schema(
    summary="更新限流规则",
    tags=['API 网关'],
)
@api_view(['PUT', 'PATCH'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_update_api(request, rule_id):
    """更新限流规则"""
    from .models import APILimitRule

    try:
        rule = APILimitRule.objects.get(id=rule_id)
    except APILimitRule.DoesNotExist:
        return Response({'code': 404, 'msg': '规则不存在'}, status=404)

    # 更新字段（仅更新传入的值）
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

    return Response({
        'code': 200,
        'msg': '规则更新成功',
        'data': {'id': str(rule.id)},
    })


@extend_schema(
    summary="删除限流规则",
    tags=['API 网关'],
)
@api_view(['DELETE'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_delete_api(request, rule_id):
    """删除限流规则"""
    from .models import APILimitRule

    try:
        rule = APILimitRule.objects.get(id=rule_id)
        rule.delete()
        return Response({'code': 200, 'msg': '规则已删除'})
    except APILimitRule.DoesNotExist:
        return Response({'code': 404, 'msg': '规则不存在'}, status=404)


@extend_schema(
    summary="切换限流规则启用状态",
    tags=['API 网关'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, HasTenantPermission])
def gateway_rule_toggle_api(request, rule_id):
    """切换规则启用/禁用"""
    from .models import APILimitRule

    try:
        rule = APILimitRule.objects.get(id=rule_id)
        rule.is_active = not rule.is_active
        rule.save()
        return Response({
            'code': 200,
            'msg': f'规则已{"启用" if rule.is_active else "禁用"}',
            'data': {'id': str(rule.id), 'is_active': rule.is_active},
        })
    except APILimitRule.DoesNotExist:
        return Response({'code': 404, 'msg': '规则不存在'}, status=404)


# ═══════════════════════════════════════════════════════════════
# 缓存管理 API
# ═══════════════════════════════════════════════════════════════

@extend_schema(
    summary="缓存命中率统计",
    description="返回缓存命中/未命中/写入/失效计数和命中率",
    tags=['缓存管理'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_stats_api(request):
    """返回当前进程的缓存命中率统计"""
    from utils.cache import CacheStats
    return Response(CacheStats.snapshot())


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
        return Response({'code': 400, 'msg': '请提供 tag 参数'}, status=400)

    valid_tags = {'dashboard', 'permissions', 'tenant', 'export', 'gateway', 'system'}
    if tag not in valid_tags:
        return Response({
            'code': 400,
            'msg': f'无效的 tag，支持: {", ".join(sorted(valid_tags))}',
        }, status=400)

    from utils.cache import invalidate_by_tag
    count = invalidate_by_tag(tag)
    return Response({'code': 200, 'msg': f'已失效 {count} 个缓存键', 'count': count})


@extend_schema(
    summary="缓存预热",
    description="执行所有已注册的预热函数",
    tags=['缓存管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_warmup_api(request):
    """触发缓存预热"""
    from utils.cache import warmup_all
    results = warmup_all(verbose=True)
    return Response({
        'code': 200,
        'msg': f'预热完成: {sum(1 for v in results.values() if v)}/{len(results)} 成功',
        'results': results,
    })


@extend_schema(
    summary="重置缓存统计",
    tags=['缓存管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def cache_reset_stats_api(request):
    """重置缓存命中率统计"""
    from utils.cache import CacheStats
    CacheStats.reset()
    return Response({'code': 200, 'msg': '统计已重置'})


# ============================================================================
# DB 连接池管理 API
# ============================================================================

@extend_schema(
    summary="DB 连接池运行指标",
    description="返回所有 alias 的池大小、活跃/空闲、命中率、超时数、错误数等。",
    tags=['系统管理'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def db_pool_stats_api(request):
    """获取所有连接池的运行指标"""
    from utils.db import pool_manager, is_patched
    stats = pool_manager.all_stats()
    return Response({
        'code': 200,
        'msg': 'ok',
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
    from utils.db.metrics import reset_all_metrics
    reset_all_metrics()
    return Response({'code': 200, 'msg': 'DB 连接池指标已重置'})


@extend_schema(
    summary="关闭并重建 DB 连接池",
    description="紧急情况下用于强制重连（如服务端连接被异常回收）。",
    tags=['系统管理'],
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemManagePermission])
def db_pool_reinit_api(request):
    """关闭所有池并重新初始化（高危操作）"""
    from utils.db import pool_manager
    pool_manager.close_all()
    n = pool_manager.init_pools()
    return Response({
        'code': 200,
        'msg': f'已重建 {n} 个连接池',
        'initialized': n,
    })
