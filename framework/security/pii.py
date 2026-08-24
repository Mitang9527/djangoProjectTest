"""
PII 脱敏工具。

用于在日志、审计、通知内容中隐藏敏感字段（手机号 / 邮箱 / 身份证 / 通用字符串）。
"""
import re

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def mask_email(value: str) -> str:
    if "@" not in value:
        return mask_generic(value)
    local, _, domain = value.partition("@")
    if len(local) <= 2:
        return f"*{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        return mask_generic(value)
    return f"{digits[:3]}****{digits[-4:]}"


def mask_generic(value: str, keep: int = 2) -> str:
    if not value:
        return value
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


def mask_pii(value: str) -> str:
    """按形态自动选择脱敏方式；无法识别则通用脱敏。"""
    if not value:
        return value
    if "@" in value and _EMAIL.match(value):
        return mask_email(value)
    if re.search(r"\d{7,}", value):
        return mask_phone(value)
    return mask_generic(value)
