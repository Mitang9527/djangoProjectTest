"""
SaaS RBAC 权限体系
==================

层级：
  User (is_superuser)  →  直通所有权限
  User (role='admin')  →  直通所有权限（兼容旧字段）
  TenantMember.role    →  由 Role.permissions 集合决定

权限粒度：
  Permission.slug 是唯一权限标识，格式建议 "<module>.<action>"
  例: "system.view" / "system.manage" / "billing.view" / "adb.operate"

用法示例：
  class MyViewSet(viewsets.ModelViewSet):
      permission_classes = [IsAuthenticated, TenantPermission('system.manage')]

  # 或直接使用预定义子类：
      permission_classes = [IsAuthenticated, SystemManagePermission]
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from rest_framework.permissions import BasePermission

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


# ---------------------------------------------------------------------------
# 权限 slug 常量 —— 与 Permission 表的 slug 字段一一对应
# ---------------------------------------------------------------------------
class PermissionSlug:
    # 系统管理
    SYSTEM_VIEW   = "system.view"
    SYSTEM_MANAGE = "system.manage"

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


# ---------------------------------------------------------------------------
# 辅助：判断用户是否为"超级管理员"
# ---------------------------------------------------------------------------
def _is_super_admin(user) -> bool:
    """
    以下任一条件满足即视为超级管理员，直通所有权限：
    1. is_superuser = True（Django 原生超管）
    2. role = 'admin'（项目自定义 User.role 字段）
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if getattr(user, "role", None) == "admin":
        return True
    return False


# ---------------------------------------------------------------------------
# 核心权限类
# ---------------------------------------------------------------------------
class HasTenantPermission(BasePermission):
    """
    基于 TenantMember → Role → Permission.slug 的 RBAC 权限检查。

    子类只需覆盖 required_slug 类属性，或通过 TenantPermission() 工厂函数动态创建。

    权限检查逻辑：
      1. 超级管理员 → 直通
      2. 用户未登录 → 拒绝
      3. 从 TenantMember 找用户在 **任意激活租户** 下的 Role（无法确定当前租户时用此降级策略）
      4. 检查 Role.permissions 中是否存在 slug = required_slug 且 is_active=True 的权限
    """

    required_slug: str | None = None   # 子类或工厂设置

    message = "您没有执行此操作的权限。"

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        user = request.user

        # 超级管理员直通
        if _is_super_admin(user):
            return True

        if not user or not user.is_authenticated:
            return False

        if not self.required_slug:
            # 没有设置 required_slug，只要登录就放行（等价于 IsAuthenticated）
            return True

        return self._user_has_slug(user, self.required_slug)

    # ------------------------------------------------------------------
    # 对象级权限（object-level）— 默认与视图级保持一致
    # ------------------------------------------------------------------
    def has_object_permission(self, request: "Request", view: "APIView", obj) -> bool:
        return self.has_permission(request, view)

    # ------------------------------------------------------------------
    # 内部：检查用户在任意激活 TenantMember 记录下是否拥有 slug
    # ------------------------------------------------------------------
    @staticmethod
    def _user_has_slug(user, slug: str) -> bool:
        """
        遍历用户在所有租户的成员记录，只要有任意一条满足即返回 True。
        如果项目后续支持"当前租户"上下文（从 JWT claims / subdomain 识别），
        可在此处传入 tenant 参数做精确匹配。
        """
        from .models import TenantMember  # 避免循环 import

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
        return False


# ---------------------------------------------------------------------------
# 工厂函数：动态生成针对特定 slug 的权限类（可缓存）
# ---------------------------------------------------------------------------
@lru_cache(maxsize=64)
def TenantPermission(slug: str) -> type[HasTenantPermission]:
    """
    动态创建一个权限类，permission_classes 可直接引用。

    用法：
        permission_classes = [IsAuthenticated, TenantPermission("system.manage")]
    """
    return type(
        f"TenantPermission_{slug.replace('.', '_')}",
        (HasTenantPermission,),
        {"required_slug": slug},
    )


# ---------------------------------------------------------------------------
# 常用预定义子类 —— 直接 import 使用，无需每次写 slug 字符串
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# ReadWrite 组合权限：GET/HEAD/OPTIONS 只需 View 权限，其余需要 Manage 权限
# ---------------------------------------------------------------------------
class ReadWriteTenantPermission(BasePermission):
    """
    复合读写权限：
    - 安全方法 (GET/HEAD/OPTIONS) → 检查 view_slug
    - 其他方法 (POST/PUT/PATCH/DELETE) → 检查 manage_slug

    用法：
        class MyViewSet(viewsets.ModelViewSet):
            permission_classes = [
                IsAuthenticated,
                ReadWriteTenantPermission.for_module("billing.order"),
            ]
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
        快捷工厂：for_module("billing.order")
        自动推断 view_slug="billing.order.view", manage_slug="billing.order.manage"
        """
        return type(
            f"ReadWritePermission_{module_prefix.replace('.', '_')}",
            (cls,),
            {
                "view_slug": f"{module_prefix}.view",
                "manage_slug": f"{module_prefix}.manage",
            },
        )
