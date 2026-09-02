"""
framework.security — 安全增强工具集。

包含：登录空闲超时(idle_timeout)、CSP 响应头中间件、PII 脱敏、
登录防爆破、密码强度校验、敏感值字段加密。
"""
from framework.security.bruteforce import (
    is_locked_out,
    record_login_failure,
    reset_login_failures,
)
from framework.security.csp import CSPMiddleware
from framework.security.password import validate_password
from framework.security.pii import mask_email, mask_phone, mask_pii
from framework.security.sensitive import (
    SensitiveField,
    decrypt_value,
    encrypt_value,
    mask_value,
)

__all__ = [
    "CSPMiddleware",
    "mask_pii",
    "mask_email",
    "mask_phone",
    "record_login_failure",
    "reset_login_failures",
    "is_locked_out",
    "validate_password",
    "SensitiveField",
    "encrypt_value",
    "decrypt_value",
    "mask_value",
]
