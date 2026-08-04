"""
API 签名验证模块
================

提供完整的 API 安全功能：
1. HMAC-SHA256 签名验证
2. 防重放攻击（nonce + timestamp）
3. 请求去重
4. 中间件、装饰器和工具函数
"""

from .core import (
    generate_signature,
    verify_signature,
    SignatureVerifier,
)
from .middleware import APISignatureMiddleware
from .decorators import require_signature, require_nonce
from .exceptions import (
    SignatureError,
    SignatureExpiredError,
    NonceUsedError,
    InvalidSignatureError,
    MissingHeaderError,
)

__all__ = [
    'generate_signature',
    'verify_signature',
    'SignatureVerifier',
    'APISignatureMiddleware',
    'require_signature',
    'require_nonce',
    'SignatureError',
    'SignatureExpiredError',
    'NonceUsedError',
    'InvalidSignatureError',
    'MissingHeaderError',
]
