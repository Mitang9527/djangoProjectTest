"""自助修改密码端点（对齐铁律 11「改密也自增 token_version」）。
流程：校验旧密码（错返回 code=old_password_wrong）→ 强度校验（5 项中 ≥4 项）→ set_password + token_version 自增（全端旧 token 失效）→ 吊销全部会话 → 为当前设备重签 access/refresh（第 8 个 JWT 签发点，当前免重登其余下线）→ SENSITIVE 审计（PASSWORD_CHANGE）。
注意：刷新 token 不校验会话记录，仅靠黑名单 + token_version 兜底，故踢其他设备必须升 token_version 而不能只吊销会话。
"""
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from framework.security.password import password_strength


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=6, max_length=64)

    def validate_new_password(self, value):
        strength = password_strength(value)
        if not strength["strong"]:
            failed = [name for name, ok in strength["checks"].items() if not ok]
            raise serializers.ValidationError(
                f"密码强度不足，未通过：{'、'.join(failed)}"
            )
        return value

    def validate(self, attrs):
        if attrs.get("old_password") == attrs.get("new_password"):
            raise serializers.ValidationError({"new_password": "新密码不能与旧密码相同"})
        return attrs


class ChangePasswordView(APIView):
    """修改本人密码：验旧设新，其他设备全部下线，当前设备重签 token 免重登。"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        if not user.check_password(old_password):
            return Response(
                {"detail": "旧密码不正确", "code": "old_password_wrong"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1. 设新密码 + token_version 自增（原子保存）
        user.set_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        user.save(update_fields=["password", "token_version"])

        # 2. 吊销全部会话（当前设备旧 token 也随版本戳失效，一并吊销）
        from system.users.models import UserSession

        revoked_count = UserSession.objects.filter(
            user=user, revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())

        # 3. 为当前设备重签 token（第 8 个 JWT 签发点，对齐 LoginService.login）
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        refresh["token_version"] = user.token_version
        from system.users.serializers import attach_tenant_claim, create_user_session

        tenant_id = attach_tenant_claim(refresh, request, user)
        # 先取 access 实例复用：属性每次访问生成新 jti，须保证会话 jti 与 access 一致
        access = refresh.access_token
        create_user_session(user, access, tenant_id, request)

        # 4. SENSITIVE 审计（PASSWORD_CHANGE）
        from system.core.audit import audit_password_change

        audit_password_change(user)

        return Response({
            "message": "密码修改成功，其他设备已下线",
            "access": str(access),
            "refresh": str(refresh),
            "revoked_sessions": revoked_count,
        })
