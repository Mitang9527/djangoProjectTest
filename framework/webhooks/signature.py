"""
入站 Webhook 签名校验（HMAC）。

用于验证第三方平台（GitHub / Stripe / 企业微信等）回调的真实性，防止伪造请求。
"""
import hashlib
import hmac


def verify_signature(
    secret: str,
    raw_body: bytes,
    signature: str,
    *,
    algorithm: str = "sha256",
    prefix: str = "sha256=",
) -> bool:
    """验证请求体签名。支持 ``sha256=<hex>`` 或纯 hex 形式。"""
    if not secret:
        return False
    if prefix and signature.startswith(prefix):
        signature = signature[len(prefix):]
    mac = hmac.new(secret.encode(), raw_body, getattr(hashlib, algorithm))
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature)


def sign_body(secret: str, raw_body: bytes, *, algorithm: str = "sha256") -> str:
    """生成本地请求的签名（测试 / 回放用）。"""
    mac = hmac.new(secret.encode(), raw_body, getattr(hashlib, algorithm))
    return f"sha256={mac.hexdigest()}"
