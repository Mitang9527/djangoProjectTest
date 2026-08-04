"""
SaaS 后台管理系统 — 页面视图（Django 模板渲染）。
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.conf import settings
from loguru import logger

from ..permissions import _is_super_admin, HasTenantPermission
from ..models import Tenant, TenantConfig, Role, Order, TenantMember
from ..services import SETTINGS_CATEGORIES


THEME_OPTIONS = [
    ('light', _('白天模式')),
    ('dark', _('夜晚模式')),
    ('system', _('跟随系统')),
]


@method_decorator(login_required, name='dispatch')
class DashboardView(View):
    template_name = 'saas/dashboard.html'

    def get(self, request, *args, **kwargs):
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
        return render(request, self.template_name, {
            'title': _('租户管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class MemberListView(View):
    template_name = 'saas/member_list.html'

    def get(self, request):
        return render(request, self.template_name, {
            'title': _('用户管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class RoleListView(View):
    template_name = 'saas/role_list.html'

    def get(self, request):
        return render(request, self.template_name, {
            'title': _('角色管理'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class PermissionListView(View):
    template_name = 'saas/permission_list.html'

    def get(self, request):
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


class SystemUserListView(View):
    """系统用户管理页面 — 展示用户列表及其租户角色关系"""

    @method_decorator(login_required)
    def get(self, request):
        tenant = getattr(request, 'tenant', None)
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


@method_decorator(login_required, name='dispatch')
class SystemDashboardView(View):
    """系统仪表盘 — 需要 system.dashboard 权限"""
    template_name = 'saas/system_dashboard.html'

    def get(self, request):
        return render(request, self.template_name, {
            'title': _('系统仪表盘'),
            'is_super_admin': _is_super_admin(request.user),
        })


@method_decorator(login_required, name='dispatch')
class SystemLogsView(View):
    """系统日志页 — 需要 system.logs.view 权限"""
    template_name = 'saas/system_logs.html'

    def get(self, request):
        from ..services import LogService
        return render(request, self.template_name, {
            'title': _('系统日志'),
            'is_super_admin': _is_super_admin(request.user),
            'log_levels': LogService.LOG_LEVELS,
        })


@method_decorator(login_required, name='dispatch')
class SystemSettingsView(View):
    """系统设置页 — 需要 system.settings.view 权限；子页各自检查"""
    template_name = 'saas/system_settings_v2.html'

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        is_super = _is_super_admin(request.user)

        accessible = {}
        for key, cat in SETTINGS_CATEGORIES.items():
            accessible[key] = is_super or HasTenantPermission._user_has_slug(
                request.user, cat['permission']
            )

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


class GatewayDashboardView(View):
    """API 网关仪表盘"""

    @method_decorator(login_required)
    def get(self, request):
        return render(request, 'saas/gateway_dashboard.html', {
            'title': 'API 网关',
            'is_super_admin': _is_super_admin(request.user),
        })


class GatewayRulesView(View):
    """限流规则管理页面"""

    @method_decorator(login_required)
    def get(self, request):
        return render(request, 'saas/gateway_rules.html', {
            'title': '限流规则管理',
            'is_super_admin': _is_super_admin(request.user),
        })
