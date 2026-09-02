"""
SaaS RBAC 权限体系：权限由 User.is_superuser / User.role(FK→Role) / TenantMember.role 三者共同决定，
超管（role.slug='super-admin'）直通所有权限；Permission.slug 唯一标识，格式 "<module>.<action>"。
用法：permission_classes = [IsAuthenticated, TenantPermission('system.manage')] 或预定义子类如 SystemManagePermission。
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from rest_framework.permissions import BasePermission

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


# 权限 slug 常量 —— 与 Permission 表的 slug 字段一一对应
class PermissionSlug:
    # 系统管理
    SYSTEM_VIEW   = "system.view"
    SYSTEM_MANAGE = "system.manage"

    # 文件资产（对齐 Fast-Vben-Admin file asset 管理）
    FILE_VIEW   = "file.view"
    FILE_MANAGE = "file.manage"

    # 租户管理
    TENANT_VIEW   = "tenant.view"
    TENANT_MANAGE = "tenant.manage"

    # 用户/成员管理
    USER_VIEW     = "user.view"
    USER_MANAGE   = "user.manage"

    # 角色 & 权限管理
    ROLE_VIEW     = "role.view"
    ROLE_MANAGE   = "role.manage"

    # 套餐 & 订阅
    PLAN_VIEW     = "billing.plan.view"
    PLAN_MANAGE   = "billing.plan.manage"
    SUBSCRIPTION_VIEW   = "billing.subscription.view"
    SUBSCRIPTION_MANAGE = "billing.subscription.manage"

    # 订单 & 发票
    ORDER_VIEW    = "billing.order.view"
    ORDER_MANAGE  = "billing.order.manage"
    INVOICE_VIEW  = "billing.invoice.view"
    INVOICE_MANAGE = "billing.invoice.manage"

    # ADB 设备管理
    ADB_VIEW    = "adb.view"
    ADB_OPERATE = "adb.operate"

    # 系统配置
    CONFIG_VIEW   = "config.view"
    CONFIG_MANAGE = "config.manage"

    # 字典管理（对齐 Fast-Vben-Admin system:dict:*）
    DICT_VIEW   = "dict.view"
    DICT_MANAGE = "dict.manage"

    # 系统仪表盘
    SYSTEM_DASHBOARD = "system.dashboard"

    # 系统日志
    SYSTEM_LOGS_VIEW   = "system.logs.view"
    SYSTEM_LOGS_MANAGE  = "system.logs.manage"

    # API 网关
    GATEWAY_VIEW   = "gateway.view"
    GATEWAY_MANAGE = "gateway.manage"

    # 系统设置（细粒度）
    SYSTEM_SETTINGS_VIEW         = "system.settings.view"
    SYSTEM_SETTINGS_BASIC        = "system.settings.basic"
    SYSTEM_SETTINGS_SECURITY     = "system.settings.security"
    SYSTEM_SETTINGS_NOTIFICATION = "system.settings.notification"
    SYSTEM_SETTINGS_INTEGRATION  = "system.settings.integration"
    SYSTEM_SETTINGS_BACKUP       = "system.settings.backup"


# 辅助：判断用户是否为"超级管理员"
def _is_super_admin(user) -> bool:
    """
    is_superuser=True 或 user.role.slug=='super-admin'（init_permissions 创建的系统角色）即超管，直通所有权限。
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    user_role = getattr(user, "role", None)
    if user_role and user_role.is_active:
        if user_role.slug == "super-admin":
            return True
    return False


# 平台级管控权限：仅超级管理员
class IsSuperAdmin(BasePermission):
    """
    仅超级管理员可访问（is_superuser=True 或 role.slug='super-admin'）。
    用于平台级管控接口——如 API 网关限流规则增删改、系统级设置等，
    普通租户成员即使拥有 gateway.manage 之类的 RBAC 权限也不可操作。
    """
    message = "仅超级管理员可执行此操作。"

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        return _is_super_admin(getattr(request, "user", None))

    def has_object_permission(self, request: "Request", view: "APIView", obj) -> bool:
        return self.has_permission(request, view)


# 核心权限类
class HasTenantPermission(BasePermission):
    """
    基于 TenantMember→Role→Permission.slug 的 RBAC 检查；子类覆盖 required_slug 或由 TenantPermission() 工厂创建。
    逻辑：超管直通 → 未登录拒绝 → 从**任意激活租户**下的成员角色查权限（无法确定当前租户时的降级策略）。
    """

    required_slug: str | None = None

    message = "您没有执行此操作的权限。"

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        user = request.user

        if _is_super_admin(user):
            return True

        if not user or not user.is_authenticated:
            return False

        if not self.required_slug:
            # 未设 required_slug：登录即放行（等价 IsAuthenticated）
            return True

        return self._user_has_slug(user, self.required_slug)

    # 对象级权限 — 默认与视图级保持一致
    def has_object_permission(self, request: "Request", view: "APIView", obj) -> bool:
        return self.has_permission(request, view)

    # 内部：检查用户在任意激活 TenantMember 记录下是否拥有 slug
    @staticmethod
    def _user_has_slug(user, slug: str) -> bool:
        """
        遍历全部租户成员记录 + 用户直接系统角色，任一满足即 True；超管（_is_super_admin）直接放行。
        """
        if _is_super_admin(user):
            return True

        from .models import TenantMember  # 避免循环 import

        # 1) 租户成员：TenantMember→Role→Permission
        members = (
            TenantMember.objects
            .filter(user=user, is_active=True)
            .select_related("role")
            .prefetch_related("role__permissions")
        )
        for member in members:
            role = member.role
            if not role or not role.is_active:
                continue
            if role.permissions.filter(slug=slug, is_active=True).exists():
                return True

        # 2) 用户直接系统角色（user.role）
        user_role = getattr(user, 'role', None)
        if user_role and user_role.is_active:
            # 已预取则遍历缓存，否则再查一次
            if hasattr(user_role, '_prefetched_objects_cache') and 'permissions' in user_role._prefetched_objects_cache:
                for perm in user_role.permissions.all():
                    if perm.slug == slug and perm.is_active:
                        return True
            elif user_role.permissions.filter(slug=slug, is_active=True).exists():
                return True

        return False


# 工厂函数：动态生成针对特定 slug 的权限类（可缓存）
@lru_cache(maxsize=64)
def TenantPermission(slug: str) -> type[HasTenantPermission]:
    """
    动态创建权限类，permission_classes 可直接引用；如 TenantPermission("system.manage")。
    """
    return type(
        f"TenantPermission_{slug.replace('.', '_')}",
        (HasTenantPermission,),
        {"required_slug": slug},
    )


# 常用预定义子类 —— 直接 import 使用，无需每次写 slug 字符串
class SystemViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_VIEW

class SystemManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_MANAGE

class TenantViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.TENANT_VIEW

class TenantManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.TENANT_MANAGE

class UserViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.USER_VIEW

class UserManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.USER_MANAGE

class DictViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.DICT_VIEW

class DictManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.DICT_MANAGE

class FileViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.FILE_VIEW

class FileManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.FILE_MANAGE

class RoleViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.ROLE_VIEW

class RoleManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.ROLE_MANAGE

class PlanViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.PLAN_VIEW

class PlanManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.PLAN_MANAGE

class OrderViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.ORDER_VIEW

class OrderManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.ORDER_MANAGE

class InvoiceViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.INVOICE_VIEW

class InvoiceManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.INVOICE_MANAGE

class AdbViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.ADB_VIEW

class AdbOperatePermission(HasTenantPermission):
    required_slug = PermissionSlug.ADB_OPERATE

class ConfigViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.CONFIG_VIEW

class ConfigManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.CONFIG_MANAGE

class SystemDashboardPermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_DASHBOARD

class SystemLogsViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_LOGS_VIEW

class SystemLogsManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_LOGS_MANAGE

class SystemSettingsViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_SETTINGS_VIEW

class SystemSettingsBasicPermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_SETTINGS_BASIC

class SystemSettingsBackupPermission(HasTenantPermission):
    required_slug = PermissionSlug.SYSTEM_SETTINGS_BACKUP

class GatewayViewPermission(HasTenantPermission):
    required_slug = PermissionSlug.GATEWAY_VIEW

class GatewayManagePermission(HasTenantPermission):
    required_slug = PermissionSlug.GATEWAY_MANAGE


# ReadWrite 组合权限：GET/HEAD/OPTIONS 只需 View 权限，其余需 Manage 权限
class ReadWriteTenantPermission(BasePermission):
    """
    复合读写权限：GET/HEAD/OPTIONS→view_slug，POST/PUT/PATCH/DELETE→manage_slug。
    用法：ReadWriteTenantPermission.for_module("billing.order")。
    """
    view_slug: str | None = None
    manage_slug: str | None = None

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

    message = "您没有执行此操作的权限。"

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        user = request.user
        if _is_super_admin(user):
            return True
        if not user or not user.is_authenticated:
            return False

        if request.method in self.SAFE_METHODS:
            slug = self.view_slug
        else:
            slug = self.manage_slug

        if not slug:
            return True

        return HasTenantPermission._user_has_slug(user, slug)

    def has_object_permission(self, request: "Request", view: "APIView", obj) -> bool:
        return self.has_permission(request, view)

    @classmethod
    @lru_cache(maxsize=32)
    def for_module(cls, module_prefix: str) -> type["ReadWriteTenantPermission"]:
        """
        快捷工厂：for_module("billing.order") → view_slug="billing.order.view"、manage_slug="billing.order.manage"
        """
        return type(
            f"ReadWritePermission_{module_prefix.replace('.', '_')}",
            (cls,),
            {
                "view_slug": f"{module_prefix}.view",
                "manage_slug": f"{module_prefix}.manage",
            },
        )


# 功能权限：自动映射（借鉴 wharttest HasModelPermission）+ 自定义 action 装饰器
def permission_required(slug: str):
    """
    为 DRF 自定义 @action 指定所需权限 slug，供 HasModelTenantPermission 读取。
    用法：@action(...) + @permission_required('billing.order.refund')；与 @action 顺序无关（functools.wraps 保留属性）。
    """
    def decorator(func):
        func.permission_required = slug
        return func
    return decorator


class HasModelTenantPermission(HasTenantPermission):
    """
    按 DRF action/HTTP 方法自动推导 slug（<module>.<action>），兼容 @permission_required（优先级最高）。
    前缀：MODULE 优先，否则 '<app_label>.<model_name>'；后缀：list/retrieve/GET→view、create/POST→add、update/PUT/PATCH→change、destroy/DELETE→delete。
    安全：无法推导模型→放行（其他权限类兜底）；有 slug 无权限→拒绝（fail-closed）。
    """

    # 自定义模块前缀；None 时从 model 自动推导
    MODULE: str | None = None

    ACTION_SUFFIX = {
        "list": "view",
        "retrieve": "view",
        "create": "add",
        "update": "change",
        "partial_update": "change",
        "destroy": "delete",
    }
    METHOD_SUFFIX = {
        "GET": "view",
        "HEAD": "view",
        "OPTIONS": "view",
        "POST": "add",
        "PUT": "change",
        "PATCH": "change",
        "DELETE": "delete",
    }

    def _derive_slug(self, request: "Request", view: "APIView") -> str | None:
        # 1) @permission_required 优先级最高
        action = getattr(view, "action", None)
        action_func = getattr(view, action, None) if action else None
        if action_func is not None and hasattr(action_func, "permission_required"):
            return action_func.permission_required

        # 2) 类属性 required_slug 兜底
        if self.required_slug:
            return self.required_slug

        # 3) 推导模块前缀
        module = self.MODULE
        if not module:
            model_cls = self._get_model(view)
            if model_cls is None:
                return None
            module = f"{model_cls._meta.app_label}.{model_cls._meta.model_name}"

        # 4) 动作 → 后缀
        suffix = self.ACTION_SUFFIX.get(action) or self.METHOD_SUFFIX.get(
            request.method, "view"
        )
        return f"{module}.{suffix}"

    @staticmethod
    def _get_model(view):
        """从 queryset / get_queryset / serializer_class 推导模型类（兼容 wharttest）。"""
        qs = getattr(view, "queryset", None)
        if qs is not None and hasattr(qs, "model"):
            return qs.model
        if hasattr(view, "get_queryset"):
            try:
                q = view.get_queryset()
                if hasattr(q, "model"):
                    return q.model
            except Exception:
                pass
        sc = getattr(view, "serializer_class", None)
        if sc is not None and hasattr(sc, "Meta") and hasattr(sc.Meta, "model"):
            return sc.Meta.model
        return None

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        user = request.user
        if _is_super_admin(user):
            return True
        if not user or not user.is_authenticated:
            return False
        slug = self._derive_slug(request, view)
        if not slug:
            return True
        return self._user_has_slug(user, slug)

    def has_object_permission(self, request: "Request", view: "APIView", obj) -> bool:
        # 对象级同样按 slug 校验（行级隔离由 IsTenantMember* 负责）
        return self.has_permission(request, view)


# 行级数据权限（成员关系隔离）——借鉴 wharttest 的 IsProjectMember/IsProjectAdmin/IsProjectOwner，适配为：
#   1. 成员关系用 TenantMember（role FK→Role），管理员/拥有者按 role__slug 匹配，slug 集合可配置；
#   2. 当前租户优先取 TenantMiddleware 注入的 request.tenant / request.tenant_id，
#      并兼容 X-Tenant-Id 请求头（JWT / 跨服务场景）。
# 用法：permission_classes = [IsAuthenticated, IsTenantMember] / [IsAuthenticated, IsTenantAdmin]
class _TenantMembershipPermission(BasePermission):
    """
    行级数据权限基类：基于 TenantMember 判定「能否访问某租户的数据」。
    集合级用 request.tenant / request.tenant_id（TenantMiddleware 注入，兼容 X-Tenant-Id 头），
    对象级用 obj.tenant / obj.tenant_id；超管直通；REQUIRED_ROLE_SLUGS 为 None 仅校验活跃成员。
    """

    REQUIRED_ROLE_SLUGS = None

    message = "您无权访问该租户的数据。"

    # 租户解析
    def _resolve_request_tenant_id(self, request: "Request"):
        """
        解析当前租户 ID，优先级：request.tenant → request.tenant_id → 请求头 X-Tenant-Id（JWT/跨服务）；无则 None。
        """
        tenant = getattr(request, "tenant", None)
        if tenant is not None and getattr(tenant, "id", None):
            return tenant.id

        tid = getattr(request, "tenant_id", None)
        if tid:
            return tid

        header = request.headers.get("X-Tenant-Id") or request.META.get("HTTP_X_TENANT_ID")
        return header or None

    @staticmethod
    def _object_tenant_id(obj) -> str | None:
        """提取对象所属租户 ID：obj.tenant_id 或 obj.tenant（FK→Tenant）。"""
        tid = getattr(obj, "tenant_id", None)
        if tid:
            return tid
        tenant = getattr(obj, "tenant", None)
        if tenant is not None:
            return getattr(tenant, "id", None)
        return None

    # 核心：成员关系校验
    def _check_membership(self, user, tenant_id: str | None) -> bool:
        if not tenant_id:
            return False
        from .models import TenantMember  # 避免循环 import

        qs = TenantMember.objects.filter(
            tenant_id=tenant_id,
            user=user,
            is_active=True,
        )
        if self.REQUIRED_ROLE_SLUGS is not None:
            qs = qs.filter(
                role__slug__in=self.REQUIRED_ROLE_SLUGS,
                role__is_active=True,
            )
        return qs.exists()

    # DRF 接口
    def has_permission(self, request: "Request", view: "APIView") -> bool:
        user = request.user
        if _is_super_admin(user):
            return True
        if not user or not user.is_authenticated:
            return False
        return self._check_membership(user, self._resolve_request_tenant_id(request))

    def has_object_permission(self, request: "Request", view: "APIView", obj) -> bool:
        user = request.user
        if _is_super_admin(user):
            return True
        # 对象级：以「对象所属租户」为准，实现真正的行级隔离
        obj_tenant_id = self._object_tenant_id(obj)
        if obj_tenant_id:
            return self._check_membership(user, obj_tenant_id)
        # 对象无 tenant 字段时，退化为请求级租户校验
        return self.has_permission(request, view)


class IsTenantMember(_TenantMembershipPermission):
    """行级数据权限：用户必须是「当前租户」的活跃成员（不限角色）。"""

    REQUIRED_ROLE_SLUGS = None
    message = "您不是该租户的成员，无权访问。"


class IsTenantAdmin(_TenantMembershipPermission):
    """
    行级数据权限：当前租户活跃成员且角色为 ('owner', 'admin') 之一；
    角色命名不同时覆盖 REQUIRED_ROLE_SLUGS（注意是父类约定的属性，非 ADMIN_ROLE_SLUGS）。
    """

    REQUIRED_ROLE_SLUGS = ("owner", "admin")
    message = "您不是该租户的管理员，无权执行此操作。"


class IsTenantOwner(_TenantMembershipPermission):
    """行级数据权限：用户必须是「当前租户」活跃成员，且角色为拥有者。"""

    REQUIRED_ROLE_SLUGS = ("owner",)
    message = "您不是该租户的拥有者，无权执行此操作。"
