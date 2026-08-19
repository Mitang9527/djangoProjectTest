"""
用户/认证应用 - 业务逻辑层。

将 views.py 中的认证、注册、用户管理等核心逻辑分离到此处，包括:
- 用户注册 (含 IP 记录、角色分配)
- 用户登录 (账号验证 + JWT 生成)
- 用户登出 (Session + JWT 黑名单双重清理)
- 用户信息获取/更新
- Token 验证
- 用户列表 (管理端，含权限过滤)

views.py 只保留: 参数提取、权限声明、渲染器选择、响应返回。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext_lazy as _
from loguru import logger

User = get_user_model()


# ============================================================
# 注册服务
# ============================================================

class RegisterService:
    """用户注册业务"""

    @staticmethod
    def register(data: Dict, request=None) -> Dict[str, Any]:
        """执行用户注册, 返回 (user, errors)"""
        from .serializers import UserRegisterSerializer

        serializer = UserRegisterSerializer(data=data)
        if not serializer.is_valid():
            logger.warning(f"注册失败: 数据验证不通过 - {serializer.errors}")
            return {"error": "validation", "errors": serializer.errors}

        user = serializer.save()

        if request:
            ip = RegisterService._get_client_ip(request)
            logger.success(
                f"新用户注册成功: 用户名=[{user.username}], IP=[{ip}]"
            )

        return {"user": user, "data": serializer.data}

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


# ============================================================
# 登录服务
# ============================================================

class LoginService:
    """用户登录业务 — JWT + Session 双通道"""

    # 自定义错误状态码 (与前端约定)
    ACCOUNT_MISSING = 301
    PASSWORD_ERROR = 501

    @classmethod
    def login(cls, username: str, password: str, request=None) -> Dict[str, Any]:
        """
        用户登录。
        返回格式:
        - 成功: {"user": ..., "tokens": {"refresh": ..., "access": ...}}
        - 账号不存在: {"error": "account_missing"}
        - 密码错误: {"error": "password_error"}
        - 已禁用: {"error": "disabled"}
        """
        # 1. 检查账号是否存在 (区分"账号不存在"和"密码错误", 提升 UX)
        if not User.objects.filter(username=username).exists():
            logger.warning(f"登录失败: 账号不存在 - [{username}]")
            return {"error": "account_missing", "message": str(_("账号不存在"))}

        # 2. 验证账号密码
        user = authenticate(username=username, password=password)

        if user is None:
            logger.warning(f"登录失败: 密码错误 - [{username}]")
            return {"error": "password_error", "message": str(_("密码错误"))}

        if not user.is_active:
            logger.warning(f"登录失败: 账号已被禁用 - [{username}]")
            return {"error": "disabled", "message": str(_("该账号已被禁用"))}

        # 3. 登录成功 — 生成 JWT
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        tokens = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

        if request:
            ip = cls._get_client_ip(request)
            logger.success(
                f"用户登录成功: 用户名=[{user.username}], "
                f"角色=[{getattr(user, 'role', 'user')}], IP=[{ip}]"
            )

        return {
            "user": user,
            "tokens": tokens,
            "user_info": {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "nickname": getattr(user, "nickname", ""),
                "role": getattr(user, "role", "user"),
            },
        }

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


# ============================================================
# 登出服务
# ============================================================

class LogoutService:
    """用户登出 — JWT + Session + API Token 三重清理"""

    @staticmethod
    def logout(request, refresh_token: Optional[str] = None) -> Dict[str, Any]:
        """
        全面登出: Session + JWT 黑名单 + API Token 清理。
        即使某个环节失败也继续，确保用户登出体验不受影响。
        """
        username: Optional[str] = None

        # 1. 获取用户信息
        if request.user and request.user.is_authenticated:
            username = request.user.username

            # 1.1 删除旧的 API Token
            try:
                from rest_framework.authtoken.models import Token
                Token.objects.filter(user=request.user).delete()
            except Exception as e:
                logger.warning(f"删除 API Token 失败: {e}")

            # 1.2 清理用户模型中的 token 字段
            if hasattr(request.user, "token") and request.user.token:
                request.user.token = None
                request.user.save(update_fields=["token"])

            # 1.3 退出 Django Session
            from django.contrib.auth import logout as django_logout
            django_logout(request)

        # 2. JWT refresh token 加入黑名单
        if refresh_token:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken
                token = RefreshToken(refresh_token)
                token.blacklist()
                logger.info("JWT Token 已加入黑名单")
            except Exception as e:
                logger.warning(f"JWT Token 黑名单处理失败: {e}")

        if username:
            logger.info(f"用户登出成功: {username}")
        else:
            logger.info("匿名用户登出请求")

        return {"success": True, "username": username}


# ============================================================
# 用户信息服务
# ============================================================

class ProfileService:
    """用户个人信息管理"""

    @staticmethod
    def update_profile(user, data: Dict, partial: bool = True) -> Dict[str, Any]:
        """更新用户个人资料"""
        from .serializers import UserDetailSerializer

        serializer = UserDetailSerializer(user, data=data, partial=partial)
        if not serializer.is_valid():
            logger.warning(f"更新用户信息失败: {serializer.errors}")
            return {"error": "validation", "errors": serializer.errors}

        instance = serializer.save()
        logger.success(f"用户信息更新成功: {instance.username}")
        return {"user": instance, "data": serializer.data}

    @staticmethod
    def get_user_detail(user, pk=None) -> Dict[str, Any]:
        """获取用户详情 (支持查看自己或指定用户)"""
        from .serializers import UserDetailSerializer

        if pk:
            target = User.objects.get(pk=pk)
        else:
            target = user

        serializer = UserDetailSerializer(target)
        return {"user": target, "data": serializer.data}


# ============================================================
# Token 验证
# ============================================================

class TokenService:
    """Token 验证与刷新"""

    @staticmethod
    def verify(request) -> Dict[str, Any]:
        """验证当前 Token 是否有效, 返回用户信息"""
        user = request.user
        return {
            "valid": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role_id": str(user.role.id) if user.role else None,
                "role_name": user.role.name if user.role else None,
            },
        }

    @staticmethod
    def jwt_login(username: str, password: str, request=None) -> Dict[str, Any]:
        """
        JWT 专用登录 (SimpleJWT 标准流程)。
        与 LoginService.login 的区别: 不走 Session, 纯 JWT。
        """
        from rest_framework_simplejwt.tokens import RefreshToken

        user = authenticate(username=username, password=password)
        if not user:
            return {"error": "auth_failed", "message": "认证失败"}

        if not user.is_active:
            return {"error": "disabled", "message": "账号已被禁用"}

        refresh = RefreshToken.for_user(user)

        if request:
            ip = (
                request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                or request.META.get("REMOTE_ADDR", "unknown")
            )
            logger.success(f"JWT登录成功: 用户名=[{username}], IP=[{ip}]")

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "nickname": getattr(user, "nickname", ""),
            },
        }


# ============================================================
# 用户管理 (管理员端)
# ============================================================

class UserManageService:
    """系统用户管理 CRUD"""

    @staticmethod
    def get_queryset(request_user):
        """根据权限返回用户查询集"""
        from system.saas.permissions import _is_super_admin

        if _is_super_admin(request_user):
            return User.objects.select_related("role").all()
        return User.objects.filter(id=request_user.id)

    @staticmethod
    def delete_user(instance, request_user) -> None:
        """删除用户 (禁止删自己)"""
        if instance == request_user:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("不能删除自己的账号")
        instance.delete()

    @staticmethod
    def get_system_roles() -> List[Dict]:
        """获取系统角色列表 (tenant=null), 无角色时自动初始化"""
        from django.apps import apps

        Role = apps.get_model("saas", "Role")

        if not Role.objects.filter(tenant__isnull=True).exists():
            from django.core.management import call_command
            try:
                call_command("init_permissions")
                logger.info("已自动运行 init_permissions 初始化系统角色")
            except Exception as e:
                logger.error(f"运行 init_permissions 失败: {e}")
                # 兜底: 创建空壳 super-admin 角色
                from system.saas.models import Permission as PermModel
                admin_role = Role.objects.create(
                    tenant=None,
                    name="超级管理员",
                    slug="super-admin",
                    description="系统超级管理员，拥有所有权限（由系统自动创建）",
                    is_system=True,
                    is_active=True,
                )
                all_perms = PermModel.objects.filter(is_active=True)
                if all_perms.exists():
                    admin_role.permissions.set(all_perms)

        roles = Role.objects.filter(tenant__isnull=True, is_active=True)
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "slug": r.slug,
                "description": r.description,
                "is_system": r.is_system,
                "is_active": r.is_active,
            }
            for r in roles
        ]
