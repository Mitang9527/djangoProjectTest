"""
解耦式 JWT 认证。

设计目标
--------
- 本服务**不维护用户表**，只信任主平台签发的 JWT。
- 校验 JWT 签名与有效期通过后，从 token claims 中读取 ``user_id`` / ``username``
  构造一个轻量 ``AuthUser`` 对象（非数据库模型），直接作为 ``request.user``。
- 因此：用户身份由主平台 SSO 负责，AI 服务只认 token，彼此完全解耦、可独立扩缩容。

前置条件
--------
- 主平台与本项目使用**同一套 SIGNING_KEY** 签发/校验 access token
  （通过环境变量 ``JWT_SIGNING_KEY`` 注入，见 settings.SIMPLE_JWT）。
- token 的负载需包含 ``user_id``（USER_ID_CLAIM）声明。
"""
from __future__ import annotations

from rest_framework.authentication import BaseAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings as jwt_settings


class AuthUser:
    """无数据库依赖的轻量用户对象，仅承载身份标识。

    提供 Django/DRF 认证链路所需的最小接口（is_authenticated / id / pk 等）。
    """

    is_authenticated = True
    is_active = True

    def __init__(self, user_id, username: str = "", email: str = ""):
        self.id = user_id
        self.pk = user_id
        self.user_id = user_id
        self.username = username
        self.email = email

    def __str__(self) -> str:
        return self.username or str(self.id)


class ServiceJWTAuthentication(BaseAuthentication):
    """校验共享密钥 JWT，返回 AuthUser（不查库）。

    复用 SimpleJWT 的解码与验签能力，但**跳过**其默认的用户库回查
    （SimpleJWT 原生会把 user_id 反查到 User 表，本服务没有该表）。
    """

    def authenticate(self, request):
        # 借用 SimpleJWT 的解析/验签能力
        base = JWTAuthentication()
        header = base.get_header(request)
        if header is None:
            return None
        raw_token = base.get_raw_token(header)
        if raw_token is None:
            return None
        try:
            validated_token = base.get_validated_token(raw_token)
        except Exception:
            return None

        user_id = validated_token.get(jwt_settings.USER_ID_CLAIM)
        if user_id is None:
            return None

        user = AuthUser(
            user_id=user_id,
            username=validated_token.get("username", "") or "",
            email=validated_token.get("email", "") or "",
        )
        return (user, validated_token)

    def authenticate_header(self, request):
        # 关键：返回非空字符串，DRF 才会把未认证响应保留为 401（而非降级为 403），
        # 并自动在响应上附加 ``WWW-Authenticate`` 头，前端据此触发 SSO 重新登录。
        return 'Bearer realm="ai-studio"'
