"""
密码强度校验。

提供轻量策略（长度 / 大小写 / 数字 / 特殊字符），可在注册、改密接口复用，
也可作为 Django AUTH_PASSWORD_VALIDATORS 的补充。
"""
import re

from django.conf import settings

STRENGTH_CHECK_LABELS = {
    "length": "长度",
    "upper": "大写字母",
    "lower": "小写字母",
    "digit": "数字",
    "special": "特殊字符",
}


def password_strength(password: str) -> dict:
    checks = {
        "length": len(password or "") >= getattr(settings, "PASSWORD_MIN_LEN", 8),
        "upper": bool(re.search(r"[A-Z]", password or "")),
        "lower": bool(re.search(r"[a-z]", password or "")),
        "digit": bool(re.search(r"\d", password or "")),
        "special": bool(re.search(r"[^\w]", password or "")),
    }
    score = sum(checks.values())
    return {"checks": checks, "score": score, "strong": score >= 4}


def validate_password(password: str) -> list:
    """返回未通过的检查项列表；空列表表示通过。"""
    return [name for name, ok in password_strength(password)["checks"].items() if not ok]
