"""用户/认证应用业务逻辑层：认证、注册、登出、用户管理等核心逻辑（views 只保留参数提取/权限/渲染/响应）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext_lazy as _
from loguru import logger

# 租户级登录日志（显式落库，避免信号双写）
from system.core.audit import record_login_log

User = get_user_model()


def verify_mfa_for_login(user, mfa_code: str) -> tuple:
    """登录链 MFA 双因子校验（对齐 Fast-Vben-Admin core/mfa.py）。返回 (ok, reason)：
    (True,None) 通过（未启用 MFA，或 TOTP/恢复码任一成功）；
    (False,'mfa_required') 已启用 MFA 未携带 mfa_code（前端应弹 TOTP 输入）；
    (False,'mfa_failed') 校验失败。调用方负责：失败记限流与登录日志，成功清零。
    """
    if not getattr(user, "mfa_enabled", False):
        return True, None

    code = (mfa_code or "").strip()
    if not code:
        return False, "mfa_required"

    from framework.security.mfa import (
        decrypt_secret, verify_totp_code, consume_recovery_code,
        get_recovery_code_count,
    )
    try:
        if user.mfa_secret_encrypted:
            secret = decrypt_secret(user.mfa_secret_encrypted)
            if verify_totp_code(secret=secret, code=code):
                return True, None
    except ValueError as exc:
        # SECRET_KEY 轮换致密钥无法解密：恢复码哈希同失效，按失败处理并告警（只能管理员兜底禁用 MFA）
        logger.error(f"MFA 密钥解密失败 user_id={user.pk}: {exc}")

    # 2) 恢复码一次性消费：命中则移除哈希并持久化
    remaining = consume_recovery_code(user.mfa_recovery_code_hashes, code)
    if remaining is not None:
        user.mfa_recovery_code_hashes = remaining
        user.save(update_fields=["mfa_recovery_code_hashes"])
        logger.info(f"MFA 恢复码消费 user_id={user.pk} 剩余={get_recovery_code_count(remaining)}")
        return True, None

    return False, "mfa_failed"


# 注册服务

class RegisterService:
    """用户注册业务"""

    @staticmethod
    def register(data: Dict, request=None) -> Dict[str, Any]:
        """执行用户注册，返回 {"user","data"} 或 {"error","errors"}"""
        from .serializers import UserRegisterSerializer

        serializer = UserRegisterSerializer(data=data)
        if not serializer.is_valid():
            logger.warning("注册失败: 数据验证不通过 - {}", serializer.errors)
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


# 登录服务

class LoginService:
    """用户登录业务 — JWT + Session 双通道"""

    # 自定义错误状态码（与前端约定）
    ACCOUNT_MISSING = 301
    PASSWORD_ERROR = 501

    @classmethod
    def login(cls, username: str, password: str, request=None,
              mfa_code: str = None) -> Dict[str, Any]:
        """
        用户登录。成功: {"user", "tokens":{"refresh","access"}}；
        失败: {"error": "account_missing"|"password_error"|"disabled"|"rate_limited"|"mfa_required"|"mfa_failed"}。
        """
        from framework.gateway.login_throttle import LoginThrottleService

        # 0. 限流预检：IP/用户名任一维度锁定→拒绝（防暴力破解）
        if LoginThrottleService.is_login_rate_limited(request, username):
            logger.warning(f"登录失败: 触发登录限流 - [{username}]")
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='rate_limited')
            return {"error": "rate_limited", "message": str(_("尝试过于频繁，请稍后再试"))}

        # 1. 检查账号是否存在（区分不存在/密码错，提升 UX）
        user = User.objects.filter(username=username).first()
        if user is None:
            logger.warning(f"登录失败: 账号不存在 - [{username}]")
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='account_missing')
            return {"error": "account_missing", "message": str(_("账号不存在"))}

        # 2. 禁用预检：is_active=False 时 ModelBackend 返回 None，须提前拦截以区分 disabled/password_error
        if not user.is_active:
            logger.warning(f"登录失败: 账号已被禁用 - [{username}]")
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='disabled')
            return {"error": "disabled", "message": str(_("该账号已被禁用"))}

        user = authenticate(username=username, password=password)
        if user is None:
            logger.warning(f"登录失败: 密码错误 - [{username}]")
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='password_error')
            return {"error": "password_error", "message": str(_("密码错误"))}

        # 3.5 MFA 校验：启用 MFA 须同请求携带 mfa_code（TOTP/恢复码）；失败计入限流
        mfa_ok, mfa_reason = verify_mfa_for_login(user, mfa_code)
        if not mfa_ok:
            logger.warning(f"登录失败: MFA 校验{mfa_reason} - [{username}]")
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='mfa_failed')
            return {
                "error": mfa_reason,  # 'mfa_required' | 'mfa_failed'
                "message": str(_("需要二次验证")) if mfa_reason == "mfa_required"
                           else str(_("二次验证失败")),
            }

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
        if hasattr(user, "token_version"):
            user.token_version = (user.token_version or 0) + 1
            user.save(update_fields=["token_version"])
            refresh["token_version"] = user.token_version
        # 多租户 claim：请求体 tenant_id 优先，否则默认租户
        from .serializers import attach_tenant_claim, create_user_session

        tenant_id = attach_tenant_claim(refresh, request, user)
        # 注意：access 属性每次访问新建实例（新 jti），须先取实例复用，保证 access 与会话 jti 一致
        access = refresh.access_token
        tokens = {
            "refresh": str(refresh),
            "access": str(access),
        }
        # 会话记录（jti 绑定 user+tenant）：切租户/登出吊销后旧 access 失效
        create_user_session(user, access, tenant_id, request, notify_new_device=True)

        if request:
            ip = cls._get_client_ip(request)
            logger.success(
                f"用户登录成功: 用户名=[{user.username}], "
                f"角色=[{getattr(user, 'role', 'user')}], IP=[{ip}]"
            )

        record_login_log(
            email=user.email or user.username, status='success',
            user=user, tenant_id=tenant_id, request=request,
        )

        # 成功清零 IP/用户名双维度计数
        LoginThrottleService.clear_failed_login_attempts(request, username)

        return {
            "user": user,
            "tokens": tokens,
            "user_info": {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "nickname": getattr(user, "nickname", ""),
                "role": getattr(user, "role", "user"),
                "tenant_id": tenant_id,
            },
        }

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


# 登出服务

class LogoutService:
    """用户登出 — JWT + Session + API Token 三重清理"""

    @staticmethod
    def logout(request, refresh_token: Optional[str] = None) -> Dict[str, Any]:
        """全面登出：Session+JWT 黑名单+会话吊销+API Token 清理，任一环节失败也继续。
        注意：django_logout 会将 request.user 置为 AnonymousUser，会话吊销须在登出前用缓存的 user 执行。"""
        username: Optional[str] = None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            username = user.username

            # 0. 吊销当前 access 对应会话（jti→revoked_at），access 立即失效（不依赖黑名单）
            try:
                auth = getattr(request, "auth", None)
                if auth is not None and hasattr(auth, "payload"):
                    jti = auth.payload.get("jti")
                    if jti:
                        from system.users.models import UserSession
                        from django.utils import timezone as dj_tz

                        UserSession.objects.filter(
                            user=user, token_jti=jti, revoked_at__isnull=True
                        ).update(revoked_at=dj_tz.now())
            except Exception as e:
                logger.warning(f"吊销会话记录失败: {e}")

            # 1.1 删除旧 API Token
            try:
                from rest_framework.authtoken.models import Token
                Token.objects.filter(user=user).delete()
            except Exception as e:
                logger.warning(f"删除 API Token 失败: {e}")

            if hasattr(user, "token") and user.token:
                user.token = None
                user.save(update_fields=["token"])

            # 1.3 退出 Session（注意：执行后 request.user 变 AnonymousUser）
            from django.contrib.auth import logout as django_logout
            django_logout(request)

        # 3. refresh token 加入黑名单
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


# 用户信息服务

class ProfileService:
    """用户个人信息管理"""

    @staticmethod
    def update_profile(user, data: Dict, partial: bool = True) -> Dict[str, Any]:
        """更新用户个人资料"""
        from .serializers import UserDetailSerializer

        serializer = UserDetailSerializer(user, data=data, partial=partial)
        if not serializer.is_valid():
            logger.warning("更新用户信息失败: {}", serializer.errors)
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


# Token 验证

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
    def jwt_login(username: str, password: str, request=None,
                  mfa_code: str = None) -> Dict[str, Any]:
        """JWT 专用登录（SimpleJWT 标准流程）；与 LoginService.login 区别：不走 Session，纯 JWT。"""
        from rest_framework_simplejwt.tokens import RefreshToken
        from framework.gateway.login_throttle import LoginThrottleService

        # 限流预检：IP/用户名任一维度锁定→拒绝（防暴力破解）
        if LoginThrottleService.is_login_rate_limited(request, username):
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='rate_limited')
            return {"error": "rate_limited", "message": "尝试过于频繁，请稍后再试"}

        user = User.objects.filter(username=username).first()
        if user is None:
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='auth_failed')
            return {"error": "auth_failed", "message": "认证失败"}

        # 禁用预检：is_active=False 时 ModelBackend 返回 None，须提前拦截以区分 disabled/auth_failed
        if not user.is_active:
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='disabled')
            return {"error": "disabled", "message": "账号已被禁用"}

        user = authenticate(username=username, password=password)
        if user is None:
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='auth_failed')
            return {"error": "auth_failed", "message": "认证失败"}

        # MFA 校验（同 LoginService.login，失败计入限流）
        mfa_ok, mfa_reason = verify_mfa_for_login(user, mfa_code)
        if not mfa_ok:
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='mfa_failed')
            return {
                "error": mfa_reason,
                "message": "需要二次验证" if mfa_reason == "mfa_required"
                           else "二次验证失败",
            }

        refresh = RefreshToken.for_user(user)
        # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
        if hasattr(user, "token_version"):
            user.token_version = (user.token_version or 0) + 1
            user.save(update_fields=["token_version"])
            refresh["token_version"] = user.token_version
        # 多租户 claim：请求体 tenant_id 优先，否则默认租户
        from .serializers import attach_tenant_claim, create_user_session

        tenant_id = attach_tenant_claim(refresh, request, user)
        # 先取 access 实例复用（属性每次访问生成新 jti）
        access = refresh.access_token
        # 会话记录（jti 绑定 user+tenant）：切租户/登出吊销后旧 access 失效
        create_user_session(user, access, tenant_id, request, notify_new_device=True)

        if request:
            ip = (
                request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                or request.META.get("REMOTE_ADDR", "unknown")
            )
            logger.success(f"JWT登录成功: 用户名=[{username}], IP=[{ip}]")

        record_login_log(
            email=user.email or user.username, status='success',
            user=user, tenant_id=tenant_id, request=request,
        )

        # 成功清零 IP/用户名双维度计数
        LoginThrottleService.clear_failed_login_attempts(request, username)

        return {
            "refresh": str(refresh),
            "access": str(access),
            "user": {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "nickname": getattr(user, "nickname", ""),
                "tenant_id": tenant_id,
            },
        }


# 用户管理（管理员端）

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
                # 兜底：创建空壳 super-admin 角色
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


# MFA 双因子认证（对齐 Fast-Vben-Admin core/mfa.py）

class MfaService:
    """MFA TOTP 绑定/启用/禁用/恢复码管理。
    状态机：setup(生成 secret+恢复码,pending) → confirm(TOTP 置 enabled) → disable(验证后清空) / recovery(TOTP 重发恢复码)。
    安全约束：已启用 MFA 调 setup/disable/recovery 须通过当前 MFA 验证（防账号被盗后一键关停）。"""

    @staticmethod
    def status(user) -> Dict[str, Any]:
        """查询当前用户 MFA 状态（不暴露密钥本身）。"""
        from framework.security.mfa import get_recovery_code_count

        return {
            "mfa_enabled": bool(user.mfa_enabled),
            "mfa_confirmed_at": user.mfa_confirmed_at,
            "recovery_codes_remaining": (
                get_recovery_code_count(user.mfa_recovery_code_hashes)
                if user.mfa_enabled else 0
            ),
        }

    @staticmethod
    def setup(user, mfa_code: str = None) -> Dict[str, Any]:
        """生成新 TOTP 绑定+恢复码（pending 未启用）。
        已启用 MFA 须提供当前 TOTP/恢复码（防劫持换绑）；secret/URI/恢复码明文仅此一次展示。"""
        from rest_framework.exceptions import ValidationError
        from framework.security.mfa import (
            generate_totp_secret, build_totp_uri, encrypt_secret,
            generate_recovery_codes, serialize_recovery_codes,
        )

        if user.mfa_enabled:
            ok, reason = verify_mfa_for_login(user, mfa_code)
            if not ok:
                raise ValidationError(
                    {"detail": "MFA 验证失败，无法重新绑定",
                     "code": "mfa_failed" if reason == "mfa_failed" else "mfa_required"}
                )

        secret = generate_totp_secret()
        recovery_codes = generate_recovery_codes()
        user.mfa_secret_encrypted = encrypt_secret(secret)
        user.mfa_recovery_code_hashes = serialize_recovery_codes(recovery_codes)
        user.mfa_enabled = False
        user.mfa_confirmed_at = None
        user.save(update_fields=[
            "mfa_secret_encrypted", "mfa_recovery_code_hashes",
            "mfa_enabled", "mfa_confirmed_at",
        ])
        logger.success(f"MFA 绑定已生成（待确认）user_id={user.pk}")

        return {
            "secret": secret,
            "uri": build_totp_uri(secret=secret, account_name=user.username),
            "recovery_codes": recovery_codes,
            "mfa_enabled": False,
            "message": "请在 Authenticator App 中添加密钥，然后调用 confirm 完成绑定；恢复码请妥善保存，仅显示一次",
        }

    @staticmethod
    def confirm(user, code: str) -> Dict[str, Any]:
        """提交 6 位 TOTP 码确认绑定并启用 MFA。"""
        from rest_framework.exceptions import ValidationError
        from django.utils import timezone
        from framework.security.mfa import decrypt_secret, verify_totp_code

        if not user.mfa_secret_encrypted:
            raise ValidationError({"detail": "请先调用 setup 生成绑定", "code": "mfa_not_setup"})
        try:
            secret = decrypt_secret(user.mfa_secret_encrypted)
        except ValueError:
            raise ValidationError(
                {"detail": "MFA 密钥状态异常（可能 SECRET_KEY 已轮换），请重新绑定",
                 "code": "mfa_setup_invalid"})
        if not verify_totp_code(secret=secret, code=code):
            raise ValidationError({"detail": "验证码错误", "code": "mfa_invalid_code"})

        user.mfa_enabled = True
        user.mfa_confirmed_at = timezone.now()
        user.save(update_fields=["mfa_enabled", "mfa_confirmed_at"])
        logger.success(f"MFA 已启用 user_id={user.pk}")

        return {"mfa_enabled": True, "mfa_confirmed_at": user.mfa_confirmed_at}

    @staticmethod
    def disable(user, code: str) -> Dict[str, Any]:
        """验证 TOTP 或恢复码后禁用 MFA（清空全部 MFA 字段）。"""
        from rest_framework.exceptions import ValidationError

        if not user.mfa_enabled:
            raise ValidationError({"detail": "MFA 未启用", "code": "mfa_not_enabled"})
        ok, reason = verify_mfa_for_login(user, code)
        if not ok:
            raise ValidationError(
                {"detail": "MFA 验证失败", "code": "mfa_failed"})

        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_confirmed_at = None
        user.mfa_recovery_code_hashes = None
        user.save(update_fields=[
            "mfa_enabled", "mfa_secret_encrypted",
            "mfa_confirmed_at", "mfa_recovery_code_hashes",
        ])
        logger.success(f"MFA 已禁用 user_id={user.pk}")

        return {"mfa_enabled": False}

    @staticmethod
    def regenerate_recovery_codes(user, code: str) -> Dict[str, Any]:
        """验证 TOTP 后重新生成恢复码（旧恢复码全部作废）。"""
        from rest_framework.exceptions import ValidationError
        from framework.security.mfa import (
            decrypt_secret, verify_totp_code,
            generate_recovery_codes, serialize_recovery_codes,
        )

        if not user.mfa_enabled:
            raise ValidationError({"detail": "MFA 未启用", "code": "mfa_not_enabled"})
        try:
            secret = decrypt_secret(user.mfa_secret_encrypted)
        except ValueError:
            raise ValidationError(
                {"detail": "MFA 密钥状态异常，请重新绑定", "code": "mfa_setup_invalid"})
        if not verify_totp_code(secret=secret, code=code):
            raise ValidationError({"detail": "验证码错误", "code": "mfa_invalid_code"})

        recovery_codes = generate_recovery_codes()
        user.mfa_recovery_code_hashes = serialize_recovery_codes(recovery_codes)
        user.save(update_fields=["mfa_recovery_code_hashes"])
        logger.success(f"MFA 恢复码已重新生成 user_id={user.pk}")

        return {
            "recovery_codes": recovery_codes,
            "message": "旧恢复码已全部作废，新恢复码请妥善保存（仅显示一次）",
        }
