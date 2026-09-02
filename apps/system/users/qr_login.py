"""QR 扫码登录 — Redis CAS 状态机。
端点：PC POST tickets/（匿名建 ticket）→ GET tickets/{id}/（轮询）→ 移动端 POST tickets/{id}/confirm/（已登录确认）→ PC 一次性取 JWT。
状态机：pending→confirmed（确认时写 JWT）→ PC Lua GETDEL 原子消费一次即销毁；TTL pending 120s，confirm 后 60s。
安全：ticket_id uuid4 不可猜；confirmed 一次性取走；Redis 不可用 503 快速失败不降级；确认者须为已认证移动端用户。
"""
from __future__ import annotations

import pickle
import uuid

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from loguru import logger


class QRLoginError(Exception):
    """QR 登录业务错误（携带 HTTP 状态码与错误码）"""

    def __init__(self, message: str, status_code: int = 400, code: str = "qr_login_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


_GETDEL_SCRIPT = """
local v = redis.call('GET', KEYS[1])
if v then
    redis.call('DEL', KEYS[1])
end
return v
"""


class QRLoginService:
    """QR 扫码登录状态机（Redis CAS）"""

    KEY_PREFIX = "qr_login"
    TICKET_TTL = 120       # pending 有效期（秒）
    CONFIRMED_TTL = 60     # confirmed 后供 PC 拉取的窗口（秒）

    # Redis 可用性

    @staticmethod
    def _client():
        from framework.cache.redis_client import get_redis

        return get_redis()

    @classmethod
    def _redis_ready(cls) -> bool:
        """Redis 真实可用（_NullRedis.ping 返回 False 而非抛异常）"""
        try:
            return bool(cls._client().get_client().ping())
        except Exception:
            return False

    # 状态机

    @classmethod
    def create_ticket(cls) -> dict:
        """PC 端生成二维码 ticket（匿名调用）"""
        if not cls._redis_ready():
            raise QRLoginError(
                "QR 登录依赖 Redis，当前服务不可用", 503, "redis_unavailable"
            )
        ticket_id = uuid.uuid4().hex
        payload = {"status": "pending", "user_id": None, "jwt": None}
        ok = cls._client().set(cls._key(ticket_id), payload, ex=cls.TICKET_TTL)
        if not ok:
            raise QRLoginError("创建二维码失败，请重试", 500, "ticket_create_failed")
        logger.info(f"[QRLogin] 创建 ticket: {ticket_id}")
        return {"ticket_id": ticket_id, "expires_in": cls.TICKET_TTL}

    @classmethod
    def poll(cls, ticket_id: str) -> dict:
        """PC 端轮询（匿名）。Returns: {"status":"pending"|"expired"} 或 {"status":"confirmed","access","refresh"}（一次性交付）"""
        if not cls._redis_ready():
            raise QRLoginError(
                "QR 登录依赖 Redis，当前服务不可用", 503, "redis_unavailable"
            )
        client = cls._client()
        key = cls._key(ticket_id)
        payload = client.get(key)
        if payload is None:
            return {"status": "expired"}
        if payload.get("status") != "confirmed":
            return {"status": payload["status"]}
        # confirmed：Lua GETDEL 原子消费，防并发轮询重复拿 JWT
        raw = cls._lua_getdel(key)
        if raw is None:
            return {"status": "expired"}  # 已被并发消费
        jwt = raw.get("jwt") or {}
        logger.info(f"[QRLogin] PC 端取走确认结果: ticket={ticket_id}")
        return {
            "status": "confirmed",
            "access": jwt.get("access"),
            "refresh": jwt.get("refresh"),
        }

    @classmethod
    def confirm(cls, ticket_id: str, user, request) -> dict:
        """移动端已登录用户确认授权：签发 JWT 写入 ticket（确认后 TTL 缩短）。"""
        if not cls._redis_ready():
            raise QRLoginError(
                "QR 登录依赖 Redis，当前服务不可用", 503, "redis_unavailable"
            )
        client = cls._client()
        key = cls._key(ticket_id)
        payload = client.get(key)
        if payload is None:
            raise QRLoginError("二维码已过期或不存在，请刷新后重试", 404, "ticket_not_found")
        if payload.get("status") == "confirmed":
            raise QRLoginError("该二维码已被确认，请勿重复操作", 400, "ticket_already_confirmed")
        jwt = cls._issue_jwt(user, request)
        payload.update(status="confirmed", user_id=user.pk, jwt=jwt)
        client.set(key, payload, ex=cls.CONFIRMED_TTL)
        logger.info(f"[QRLogin] 确认登录: ticket={ticket_id}, user={user.username}")
        return {"status": "confirmed"}

    # 内部

    @classmethod
    def _key(cls, ticket_id: str) -> str:
        return f"{cls.KEY_PREFIX}:{ticket_id}"

    @classmethod
    def _lua_getdel(cls, key: str):
        """原子 GET+DEL。返回 pickle 反序列化后的 dict；键不存在/异常返回 None。"""
        try:
            raw = cls._client().get_client().eval(_GETDEL_SCRIPT, 1, key)
        except Exception:
            return None
        if raw is None or raw == 0:
            return None
        return pickle.loads(raw)

    @classmethod
    def _issue_jwt(cls, user, request) -> dict:
        """签发 JWT（收敛到统一签发链 issue_login_tokens：token_version + tenant claim + session + 登录日志）"""
        from system.users.serializers import issue_login_tokens

        return issue_login_tokens(user, request, notify_new_device=True)


# 视图

class QRLoginCreateView(APIView):
    """PC 端生成扫码登录二维码（匿名）"""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            data = QRLoginService.create_ticket()
        except QRLoginError as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status_code)
        return Response(data, status=status.HTTP_201_CREATED)


class QRLoginPollView(APIView):
    """PC 端轮询二维码状态（匿名）"""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, ticket_id):
        try:
            data = QRLoginService.poll(ticket_id)
        except QRLoginError as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status_code)
        return Response(data)


class QRLoginConfirmView(APIView):
    """移动端确认授权（已登录用户，JWT 鉴权）"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, ticket_id):
        try:
            data = QRLoginService.confirm(ticket_id, request.user, request)
        except QRLoginError as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status_code)
        return Response(data)
