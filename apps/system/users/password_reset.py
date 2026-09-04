"""找回密码（邮箱重置）。
POST reset/request/（匿名）：按 email/username 定位用户，生成一次性 token（PasswordResetTokenGenerator，HMAC 绑定密码哈希，改密后失效）→ 发邮件（uid+token 前端链接）。
防枚举：用户不存在/无邮箱/发送失败统一返回相同文案；限流：IP+email 双维度计数（成败均计）429。
POST reset/confirm/（匿名）：校验 uid+token → 强度校验 → set_password + token_version 自增（全端旧 token 失效）→ 吊销全部会话 → PASSWORD_CHANGE 审计；匿名流程不重签 token。
"""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from loguru import logger
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from framework.gateway.login_throttle import LoginThrottleService
from framework.security.password import password_strength, STRENGTH_CHECK_LABELS

# 统一防枚举文案：用户存在与否、发送成败，响应完全一致
_GENERIC_OK = "如果该邮箱已注册，我们已发送密码重置邮件"


def _resolve_user(attrs):
    """按 email（优先）或 username 定位用户；返回 None 表示不可重置。"""
    from system.users.models import User

    email = (attrs.get("email") or "").strip().lower()
    username = (attrs.get("username") or "").strip()
    if email:
        user = User.objects.filter(email__iexact=email).first()
    elif username:
        user = User.objects.filter(username=username).first()
    else:
        return None
    if user is None or not (user.email or "").strip():
        return None
    return user


def _build_reset_link(user, token: str) -> str:
    """生成前端重置页链接；未配置 FRONTEND_URL 返回空串（邮件只含 token）。"""
    base = getattr(settings, "PASSWORD_RESET_FRONTEND_URL", "") or ""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}uid={uid}&token={token}"


def _send_reset_email(user, token: str) -> bool:
    link = _build_reset_link(user, token)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    if link:
        body = (
            "您正在重置账号密码，请在 30 分钟内点击以下链接完成重置（仅一次有效）：\n\n"
            f"{link}\n\n如非本人操作，请忽略本邮件。"
        )
    else:
        body = (
            "您正在重置账号密码，请在 30 分钟内使用以下凭证调用重置接口（仅一次有效）：\n\n"
            f"uid: {uid}\ntoken: {token}\n\n如非本人操作，请忽略本邮件。"
        )
    subject = "重置您的账号密码"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    try:
        send_mail(subject, body, from_email, [user.email], fail_silently=False)
        return True
    except Exception:
        logger.exception("密码重置邮件发送失败 user_id={} email={}", user.id, user.email)
        return False


class PasswordResetRequestView(APIView):
    """请求密码重置邮件（匿名，防枚举 + IP/email 双维度限流）。"""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        username = (request.data.get("username") or "").strip()
        target = email or username
        if not target:
            return Response({"detail": "请提供 email 或 username"},
                            status=status.HTTP_400_BAD_REQUEST)

        # 限流预检：IP/email 任一维度锁定→429
        if LoginThrottleService.is_password_reset_rate_limited(request, target):
            return Response({"detail": "请求过于频繁，请稍后再试"},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        # 用户不存在/无邮箱：不发送，但同样计数（防枚举）+ 统一文案
        user = _resolve_user({"email": email, "username": username})
        if user is not None:
            token = default_token_generator.make_token(user)
            _send_reset_email(user, token)

        # 成功/失败均计数（不因成功清零，防批量探测）
        LoginThrottleService.record_password_reset_attempt(request, target)

        return Response({"message": _GENERIC_OK})


class PasswordResetConfirmView(APIView):
    """用邮件中的 uid + token 重置密码（匿名，改密后全端旧 token 失效）。"""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        uid = (request.data.get("uid") or "").strip()
        token = (request.data.get("token") or "").strip()
        new_password = request.data.get("new_password") or ""

        if not uid or not token or not new_password:
            return Response({"detail": "缺少 uid / token / new_password"},
                            status=status.HTTP_400_BAD_REQUEST)

        # uid 解码→用户（失败统一 400，不区分 uid/token 错，防探测）
        from system.users.models import User

        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, token):
            return Response({"detail": "重置链接无效或已过期，请重新发起"},
                            status=status.HTTP_400_BAD_REQUEST)

        # 强度校验（复用密码策略：5 项中 ≥4 项通过）
        strength = password_strength(new_password)
        if not strength["strong"]:
            failed_keys = [name for name, ok in strength["checks"].items() if not ok]

            failed_labels = [STRENGTH_CHECK_LABELS.get(key, key) for key in failed_keys]
            return Response({"detail": f"密码强度不足，未通过：{'、'.join(failed_labels)}"},
                            status=status.HTTP_400_BAD_REQUEST)

        # 设新密码 + token_version 自增（全端旧 token 失效）+ 吊销全部会话
        user.set_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        user.save(update_fields=["password", "token_version"])

        from system.users.models import UserSession

        UserSession.objects.filter(
            user=user, revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())

        # 敏感审计
        from system.core.audit import audit_password_change

        audit_password_change(user)
        logger.success("密码已通过邮件重置 user_id={}", user.id)

        return Response({"message": "密码已重置，请使用新密码登录"})
