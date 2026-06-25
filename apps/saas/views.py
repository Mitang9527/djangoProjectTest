"""
SaaS 后台管理系统 - 视图函数
"""
import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
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
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name='dispatch')
class PlaceholderModuleView(View):
    template_name = 'saas/saas_list.html'
    page_title = ''
    page_description = _('该模块的详细管理功能正在建设中，目前您可以看到此占位页面。')
    action_text = _('新增')

    def get_context_data(self):
        return {
            'title': self.page_title,
            'description': self.page_description,
            'action_text': self.action_text,
        }

    def get(self, request):
        return render(request, self.template_name, self.get_context_data())


@method_decorator(login_required, name='dispatch')
class TenantListView(View):
    template_name = 'saas/tenant_list.html'

    def get(self, request):
        return render(request, self.template_name, {'title': _('租户管理')})


@method_decorator(login_required, name='dispatch')
class MemberListView(View):
    template_name = 'saas/member_list.html'

    def get(self, request):
        return render(request, self.template_name, {'title': _('用户管理')})


@method_decorator(login_required, name='dispatch')
class RoleListView(View):
    template_name = 'saas/role_list.html'

    def get(self, request):
        return render(request, self.template_name, {'title': _('角色管理')})


@method_decorator(login_required, name='dispatch')
class PermissionListView(View):
    template_name = 'saas/permission_list.html'

    def get(self, request):
        return render(request, self.template_name, {'title': _('权限管理')})


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
        return {
            'title': _('系统设置'),
            'available_languages': self.get_supported_languages(),
            'theme_options': THEME_OPTIONS,
            'current_language': self.get_current_language(request),
            'current_theme': self.get_current_theme(request),
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
        is_super = request.user.is_superuser or getattr(request.user, 'role', 'user') == 'admin'

        context = {
            'title': _('系统用户'),
            'current_tenant_id': str(tenant.id) if tenant else '',
            'current_tenant_name': tenant.name if tenant else _('全部租户'),
            'all_tenants_json': '[]',
            'tenant_roles_json': '[]',
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
def me_tenants(request):
    """返回当前用户可访问的租户列表"""
    is_super = request.user.is_superuser or getattr(request.user, 'role', 'user') == 'admin'
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
