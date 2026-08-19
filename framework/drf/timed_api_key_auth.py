"""
带时效性的 API Key 认证 — 用于「先同步校验密钥正确性 + 时效性，再返回受保护信息」的接口。

设计要点：
- 从请求头提取密钥：优先 `X-API-Key: <key>`，其次 `Authorization: Bearer <key>`。
- **同步校验**：在 DRF 视图方法执行之前完成，任一不满足直接抛出 401，
  保证「无有效密钥绝不进入视图返回信息」。
- 校验维度：
    1. 密钥缺失        → 401（强制要求，不降级到其他认证后端）
    2. 密钥错误        → 401
    3. 密钥已禁用      → 401
    4. 密钥已过期(时效性) → 401
- 通过后将 APIKey 实例挂到 `request.api_key`，供视图读取（名称、过期时间等）。

用法：
    class SecureInfoView(APIView):
        authentication_classes = [TimedAPIKeyAuthentication]
        permission_classes = [AllowAny]   # 唯一闸门即本认证类
"""

from __future__ import annotations

from typing import Optional, Tuple

from django.utils import timezone
from rest_framework import authentication
from rest_framework import exceptions as drf_exceptions
from rest_framework.request import Request

HEADER_API_KEY = "HTTP_X_API_KEY"
HEADER_AUTHORIZATION = "HTTP_AUTHORIZATION"
BEARER_PREFIX = "bearer "


class TimedAPIKeyAuthentication(authentication.BaseAuthentication):
    """带时效性的 API Key 认证后端（要求密钥正确且未过期）。"""

    keyword = "Bearer"

    def authenticate(self, request: Request) -> Tuple:
        """
        同步校验密钥。成功返回 (user, raw_key)，失败抛出 AuthenticationFailed(401)。

        该方法是 DRF 认证链的一环，在视图执行前调用；抛出异常即短路，
        不会进入视图体，从而保证「先校验、后返回」。
        """
        raw_key = self._extract_key(request)
        if not raw_key:
            # 强制要求密钥：缺失即拒绝，避免无 key 直接放行
            raise drf_exceptions.AuthenticationFailed(
                "缺少访问密钥，请在请求头携带 X-API-Key 或 Authorization: Bearer <key>"
            )

        key_obj = self._verify(raw_key)

        # 同步记录最近使用时间（失败仅记日志，不影响主流程）
        try:
            key_obj.last_used_at = timezone.now()
            key_obj.save(update_fields=["last_used_at"])
        except Exception:
            pass

        # 供视图读取密钥元信息（名称、过期时间等）
        request.api_key = key_obj
        return (key_obj.user, raw_key)

    def authenticate_header(self, request: Request) -> str:
        return f'{self.keyword} realm="api"'

    # ---------------------------------------------------------------
    # 内部方法
    # ---------------------------------------------------------------

    def _extract_key(self, request: Request) -> Optional[str]:
        """从请求头提取密钥。"""
        key = request.META.get(HEADER_API_KEY, "")
        if key:
            return key.strip()

        auth = request.META.get(HEADER_AUTHORIZATION, "")
        if auth and auth.lower().startswith(BEARER_PREFIX):
            return auth[len(BEARER_PREFIX):].strip()

        return None

    def _verify(self, raw_key: str):
        """
        校验密钥正确性与时效性。

        缺失/错误/禁用/过期均抛出 AuthenticationFailed（→ 401）。
        """
        from system.core.models import APIKey

        key_hash = APIKey.hash_key(raw_key)
        try:
            key_obj = APIKey.objects.select_related("user").get(key_hash=key_hash)
        except APIKey.DoesNotExist:
            raise drf_exceptions.AuthenticationFailed("访问密钥无效")

        if not key_obj.is_active:
            raise drf_exceptions.AuthenticationFailed("访问密钥已被禁用")
        if key_obj.is_expired():
            raise drf_exceptions.AuthenticationFailed("访问密钥已过期")

        return key_obj
