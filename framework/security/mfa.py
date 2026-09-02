"""
MFA TOTP + 恢复码核心工具（对齐 Fast-Vben-Admin ``core/mfa.py``）。

能力：
  - TOTP：pyotp 生成密钥 / otpauth URI / 校验（带前后窗口容忍时钟偏移）；
  - 密钥加密：TOTP secret 落库前用 Fernet 加密（key 由 SECRET_KEY 派生，零额外配置）；
  - 恢复码：HMAC-SHA256 哈希存储（明文只展示一次），一次性消费（消费即删）。

使用方（apps/system/users 的 service / view）负责：保存 / 更新用户字段、审计日志、
登录限流计数。本模块保持纯函数，不依赖 ORM。
"""
import base64
import hashlib
import hmac
import json
import secrets

from cryptography.fernet import Fernet, InvalidToken

try:
    import pyotp
except ImportError:  # pragma: no cover - 未安装时降级为不可用
    pyotp = None

from django.conf import settings

# 恢复码数量
RECOVERY_CODE_COUNT = 10


def _fernet() -> Fernet:
    """由 SECRET_KEY 派生 Fernet key（32 字节 urlsafe base64），零额外配置。

    注意：SECRET_KEY 轮换会使已加密的 TOTP secret 无法解密（表现为
    mfa_setup_invalid），需要用户重新绑定 MFA —— 属可接受的运维副作用。
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


# ── TOTP ─────────────────────────────────────────────

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(*, secret: str, account_name: str) -> str:
    issuer = getattr(settings, "MFA_TOTP_ISSUER", "Django Enterprise Platform")
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=issuer)


def normalize_totp_code(code: str) -> str:
    return "".join(ch for ch in (code or "") if ch.isdigit())


def verify_totp_code(*, secret: str, code: str) -> bool:
    if pyotp is None or not secret or not code:
        return False
    normalized = normalize_totp_code(code)
    if len(normalized) != 6:
        return False
    window = int(getattr(settings, "MFA_TOTP_VALID_WINDOW", 0) or 1)
    return bool(pyotp.TOTP(secret).verify(normalized, valid_window=window))


# ── 密钥加密（Fernet） ────────────────────────────────

def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value_encrypted: str) -> str:
    """解密失败抛 ValueError（由调用方转译为 mfa_setup_invalid）。"""
    try:
        return _fernet().decrypt(value_encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Invalid encrypted secret") from exc


# ── 恢复码（HMAC 哈希 + 一次性消费） ──────────────────

def generate_recovery_codes(*, count: int = RECOVERY_CODE_COUNT) -> list:
    return [secrets.token_urlsafe(9).upper() for _ in range(count)]


def _hash_recovery_code(code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        code.strip().upper().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def serialize_recovery_codes(codes: list) -> str:
    return json.dumps([_hash_recovery_code(code) for code in codes])


def consume_recovery_code(recovery_codes_serialized, code: str):
    """消费一个恢复码：命中则返回「移除后的哈希列表 JSON」，未命中返回 None。"""
    if not recovery_codes_serialized or not code:
        return None
    try:
        hashes = json.loads(recovery_codes_serialized)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(hashes, list):
        return None
    expected = _hash_recovery_code(code)
    for index, stored in enumerate(hashes):
        if isinstance(stored, str) and hmac.compare_digest(stored, expected):
            hashes.pop(index)
            return json.dumps(hashes)
    return None


def get_recovery_code_count(recovery_codes_serialized) -> int:
    if not recovery_codes_serialized:
        return 0
    try:
        hashes = json.loads(recovery_codes_serialized)
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(hashes) if isinstance(hashes, list) else 0
