"""会话管理端点：列出我的登录会话 / 踢出指定设备 / 踢出其他所有设备。
GET sessions/ 我的有效会话（含 is_current）；DELETE sessions/{id}/ 吊销指定设备（禁吊销当前）；POST sessions/kick-others/ 踢出其他设备。
UserSession 每次签发 access 时记录（jti 绑定 user+tenant），认证层按 revoked_at 校验。
注意：本项目每次登录自增 token_version（单设备强语义），旧 token 本就失效；本模块的踢出是显式收口（状态归位+防御纵深）。
"""
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response


class SessionSerializer(serializers.Serializer):
    """会话输出：只读，供前端渲染设备列表。"""
    id = serializers.UUIDField()
    ip = serializers.CharField()
    user_agent = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    is_current = serializers.SerializerMethodField()
    tenant_id = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()

    def get_is_current(self, obj) -> bool:
        return obj.token_jti == self.context.get('current_jti')

    def get_tenant_id(self, obj):
        return str(obj.tenant_id) if obj.tenant_id else None

    def get_tenant_name(self, obj):
        return obj.tenant.name if obj.tenant_id else None


class SessionViewSet(viewsets.ViewSet):
    """用户自助会话管理（仅本人会话，无管理员全局视角）。"""

    permission_classes = [permissions.IsAuthenticated]

    # 内部工具
    @staticmethod
    def _current_jti(request):
        """当前请求 access token 的 jti（认证层已校验，正常必有）。"""
        auth = getattr(request, 'auth', None)
        if auth is None:
            return None
        try:
            return auth.get('jti') or None
        except Exception:
            return None

    def _active_sessions(self, user):
        from system.users.models import UserSession
        return UserSession.objects.filter(
            user=user, revoked_at__isnull=True,
        ).order_by('-created_at')[:50]

    def _session_for(self, user, pk):
        from system.users.models import UserSession
        try:
            return UserSession.objects.get(
                pk=pk, user=user, revoked_at__isnull=True,
            )
        except UserSession.DoesNotExist:
            return None

    def get_serializer(self, instance, current_jti):
        return SessionSerializer(instance, many=True, context={'current_jti': current_jti})

    # 端点
    def list(self, request):
        """列出我当前有效的登录会话（上限 50，按创建时间倒序）。"""
        current_jti = self._current_jti(request)
        qs = self._active_sessions(request.user)
        data = self.get_serializer(qs, current_jti).data
        return Response({"sessions": data, "count": len(data)})

    def destroy(self, request, pk=None):
        """吊销指定设备：置 revoked_at → 该设备 access 立即失效。"""
        current_jti = self._current_jti(request)
        if not current_jti:
            return Response(
                {"detail": "无法识别当前会话", "code": "no_current_jti"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session = self._session_for(request.user, pk)
        if session is None:
            return Response(
                {"detail": "会话不存在或已失效"},
                status=status.HTTP_404_NOT_FOUND,
            )
        if session.token_jti == current_jti:
            return Response(
                {"detail": "不能吊销当前会话，请使用退出登录", "code": "cannot_revoke_current"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at", "updated_at"])
        return Response({"message": "该设备已下线"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="kick-others")
    def kick_others(self, request):
        """吊销除当前设备外的全部有效会话。"""
        from system.users.models import UserSession

        current_jti = self._current_jti(request)
        if not current_jti:
            return Response(
                {"detail": "无法识别当前会话", "code": "no_current_jti"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        revoked = UserSession.objects.filter(
            user=request.user, revoked_at__isnull=True,
        ).exclude(token_jti=current_jti).update(revoked_at=timezone.now())
        return Response({"message": f"已下线 {revoked} 台其他设备", "revoked": revoked})
