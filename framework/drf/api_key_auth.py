"""
API Key 认证 — 为外部系统提供简单安全的认证方式。

授权方式:
    Authorization: Bearer <api_key>
    X-API-Key: <api_key>

用法:
    # settings.py 中注册
    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "framework.drf.api_key_auth.APIKeyAuthentication",
            ...
        ],
    }

    # settings.py 中配置 key 映射 (简单模式, 无需数据库)
    API_KEYS = {
        "sk-xxxx-xxxx-xxxx": "admin",         # key → username
        "mcp-external-service": "system_bot",
    }

    # 或在 Django Admin / 模型中使用 APIKey 模型 (生产模式)
    # python manage.py makemigrations && migrate
    # 然后在 Admin 界面管理 Key
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import authentication
from rest_framework import exceptions as drf_exceptions
from rest_framework.request import Request

User = get_user_model()

# ---------------------------------------------------------------
# 常量
# ---------------------------------------------------------------

HEADER_API_KEY = "HTTP_X_API_KEY"
HEADER_AUTHORIZATION = "HTTP_AUTHORIZATION"
BEARER_PREFIX = "bearer "
API_KEY_PREFIX = "sk-"

# ---------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    API Key 认证后端。

    查找顺序:
    1. Header: X-API-Key: <key>
    2. Header: Authorization: Bearer <key>

    验证顺序:
    1. settings.API_KEYS 字典 (简单模式, key→username 映射)
    2. APIKey 数据库模型 (如果存在)

    Key 支持明文和 SHA256 哈希两种形式。
    """

    keyword = "Bearer"

    def authenticate(self, request: Request):
        api_key = self._extract_key(request)
        if not api_key:
            return None  # 让下一个认证后端处理

        user = self._authenticate_by_settings(api_key)
        if user is None:
            user = self._authenticate_by_model(api_key)
        if user is None:
            raise drf_exceptions.AuthenticationFailed("无效的 API Key")

        if not user.is_active:
            raise drf_exceptions.AuthenticationFailed("用户已被禁用")

        return (user, api_key)

    def authenticate_header(self, request: Request) -> str:
        return f'{self.keyword} realm="api"'

    # ---- 内部方法 ----

    def _extract_key(self, request: Request) -> Optional[str]:
        """从请求头中提取 API Key"""
        # 优先 X-API-Key
        key = request.META.get(HEADER_API_KEY, "")
        if key:
            return key.strip()

        # 其次 Authorization: Bearer <key>
        auth = request.META.get(HEADER_AUTHORIZATION, "")
        if auth and auth.lower().startswith(BEARER_PREFIX):
            return auth[len(BEARER_PREFIX):].strip()

        return None

    def _authenticate_by_settings(self, api_key: str) -> Optional[User]:
        """从 settings.API_KEYS 字典中查找用户"""
        api_keys: dict = getattr(settings, "API_KEYS", {})
        if not api_keys:
            return None

        # 尝试明文匹配
        username = api_keys.get(api_key)
        if username:
            return self._get_user(username)

        # 尝试 SHA256 哈希匹配
        key_hash = self._hash_key(api_key)
        for stored_key, username in api_keys.items():
            if stored_key == key_hash:
                return self._get_user(username)

        return None

    def _authenticate_by_model(self, api_key: str) -> Optional[User]:
        """从 APIKey 数据库模型中查找用户"""
        try:
            from apps.system.core.models import APIKey as APIKeyModel
        except (ImportError, LookupError):
            return None

        # 先查明文
        try:
            key_obj = APIKeyModel.objects.select_related("user").get(
                key=api_key, is_active=True
            )
            if not key_obj.is_expired():
                key_obj.last_used_at = timezone.now()
                key_obj.save(update_fields=["last_used_at"])
                return key_obj.user
        except APIKeyModel.DoesNotExist:
            pass

        # 再查哈希
        key_hash = self._hash_key(api_key)
        try:
            key_obj = APIKeyModel.objects.select_related("user").get(
                key_hash=key_hash, is_active=True
            )
            if not key_obj.is_expired():
                key_obj.last_used_at = timezone.now()
                key_obj.save(update_fields=["last_used_at"])
                return key_obj.user
        except APIKeyModel.DoesNotExist:
            pass

        return None

    @staticmethod
    def _get_user(username: str) -> Optional[User]:
        """根据用户名查用户, 不存在时不抛异常"""
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            return None

    @staticmethod
    def _hash_key(key: str) -> str:
        """对 API Key 做 SHA256 哈希"""
        return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------


def generate_api_key(prefix: str = API_KEY_PREFIX) -> str:
    """
    生成安全的 API Key。

    格式: sk-{32位随机hex}

    示例:
        >>> generate_api_key()
        'sk-a1b2c3d4e5f6...'
    """
    random_part = secrets.token_hex(16)
    return f"{prefix}{random_part}"


# ---------------------------------------------------------------
# drf-spectacular 扩展
# ---------------------------------------------------------------
# 为 APIKeyAuthentication 注册 OpenAPI 安全方案, 消除 schema 生成时的
# "could not resolve authenticator" 警告。drf-spectacular 在类定义时自动
# 将其登记进扩展注册表, 无需在 SPECTACULAR_SETTINGS 中额外声明。


try:
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class APIKeyAuthenticationScheme(OpenApiAuthenticationExtension):
        """APIKeyAuthentication 的 OpenAPI 认证扩展。"""

        target_class = "framework.drf.api_key_auth.APIKeyAuthentication"
        name = "APIKeyAuth"  # components.securitySchemes 中的方案名

        def get_security_definition(self, auto_schema):
            return {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": (
                    "API Key 认证。支持两种方式之一: "
                    "请求头 `X-API-Key: <key>` 或 `Authorization: Bearer <key>`。"
                ),
            }
except ImportError:  # drf-spectacular 未安装时静默跳过, 不影响认证本身
    pass


# ---------------------------------------------------------------
# APIKey 模型 (可选, 在 core app 中定义)
# ---------------------------------------------------------------
# 如需模型支持, 在 apps/core/models.py 中添加:
#
# class APIKey(models.Model):
#     user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="api_keys")
#     name = models.CharField(max_length=100, help_text="标识用途")
#     key = models.CharField(max_length=128, unique=True, help_text="明文 Key (仅创建时可见)")
#     key_hash = models.CharField(max_length=64, unique=True, help_text="SHA256 哈希")
#     is_active = models.BooleanField(default=True)
#     expires_at = models.DateTimeField(null=True, blank=True)
#     last_used_at = models.DateTimeField(null=True, blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#
#     def is_expired(self) -> bool:
#         return self.expires_at is not None and timezone.now() > self.expires_at
