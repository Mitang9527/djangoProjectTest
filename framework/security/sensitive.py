"""
敏感值字段加密（对齐 Fast-Vben-Admin ``platform/sensitive_values.py``，并复用
``framework.key_management.key_rotation`` 的多密钥能力）。

能力：
  - 版本化密文：``v1:<ciphertext>``，未来算法升级可平滑迁移（新版本前缀兼容旧数据）；
  - 多密钥轮换：加密用当前主密钥，解密依次尝试所有活跃密钥 ——
    SECRET_KEY 轮换后旧密文仍可解密（强于 mfa.py 的单密钥实现）；
  - Django 模型字段：``SensitiveField(TextField)`` 落库自动加密、读库自动解密；
  - 序列化脱敏：``mask_value()`` 复用 ``framework.security.pii``，API 输出不泄露明文。

使用约束（与所有对称加密字段一致）：
  - 密文字段不可用于 ORM filter/exact 查询、order_by、唯一约束（明文不可见）；
  - 不可逆凭证（如 MFA 恢复码）仍用 HMAC 哈希（见 mfa.py），本模块只做可逆加密。
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.db import models

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 非 Django 上下文（脚本）时降级
    from framework.key_management.key_rotation import (
        get_all_secret_keys,
        get_rotatable_secret_key,
    )
except Exception:  # pragma: no cover
    get_all_secret_keys = None
    get_rotatable_secret_key = None

_CURRENT_VERSION = "v1"
_VERSION_PREFIX = f"{_CURRENT_VERSION}:"


def _derive_fernet(key: str) -> Fernet:
    """由任意密钥派生 Fernet key（32 字节 urlsafe base64），与 mfa.py 同算法。"""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _primary_key() -> str:
    """当前主密钥：优先 key_rotation 托管的主密钥，回退 django SECRET_KEY。"""
    if get_rotatable_secret_key is not None:
        try:
            key = get_rotatable_secret_key()
            if key:
                return key
        except Exception as exc:  # pragma: no cover - 防御 key_rotation 异常
            logger.warning("key_rotation primary key unavailable: %s", exc)
    from django.conf import settings

    return settings.SECRET_KEY


def _candidate_keys() -> list[str]:
    """解密候选密钥：所有活跃密钥 + SECRET_KEY 兜底（保序去重）。"""
    keys: list[str] = []
    if get_all_secret_keys is not None:
        try:
            keys = list(get_all_secret_keys())
        except Exception as exc:  # pragma: no cover - 防御 key_rotation 异常
            logger.warning("key_rotation active keys unavailable: %s", exc)
    from django.conf import settings

    if settings.SECRET_KEY and settings.SECRET_KEY not in keys:
        keys.append(settings.SECRET_KEY)
    return keys


def encrypt_value(value: str) -> str:
    """使用当前主密钥加密，返回 ``v1:<ciphertext>``；空值原样返回。"""
    if not value:
        return value
    cipher = _derive_fernet(_primary_key()).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_VERSION_PREFIX}{cipher}"


def decrypt_value(protected: str) -> str:
    """解密 ``v1:<ciphertext>``；依次尝试所有活跃密钥，全部失败抛 InvalidToken。"""
    if not protected:
        return protected
    if not protected.startswith(_VERSION_PREFIX):
        raise InvalidToken(f"Unsupported/unknown version prefix: {protected[:8]!r}")
    ciphertext = protected[len(_VERSION_PREFIX) :]
    last_error: InvalidToken | None = None
    for key in _candidate_keys():
        try:
            return _derive_fernet(key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            last_error = exc
    raise last_error or InvalidToken("No candidate key available")


def mask_value(value: str, keep: int = 2) -> str:
    """通用脱敏，供序列化输出使用（复用 framework.security.pii.mask_generic）。"""
    if not value:
        return value
    from framework.security.pii import mask_generic

    return mask_generic(value, keep=keep)


class SensitiveField(models.TextField):
    """
    透明加密的文本字段：落库为 ``v1:Fernet`` 密文，读库自动解密为明文。

    用法::

        class ProviderConfig(models.Model):
            api_secret = SensitiveField(blank=True, default="")

    注意：密文不可见，故该字段不能参与 filter/exact 查询、order_by 与唯一约束。
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value or value.startswith(_VERSION_PREFIX):
            # 空值透传；已是密文则幂等（防止二次加密）
            return value
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        return decrypt_value(value)
