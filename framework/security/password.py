"""
密码强度校验。

提供轻量策略（长度 / 大小写 / 数字 / 特殊字符），可在注册、改密接口复用，
也可作为 Django AUTH_PASSWORD_VALIDATORS 的补充。
"""
import re

from django.conf import settings


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
    """返回未通过的检查项列表（原始键名）；空列表表示通过。"""
    return [name for name, ok in password_strength(password)["checks"].items() if not ok]


def describe_weakness(password: str) -> list:
    """未通过项的中文可读描述；空列表表示通过。

    校验键名（length/upper/...）不能直接回给终端用户，统一在此转成中文。
    长度项动态读取 PASSWORD_MIN_LEN，避免与 password_strength 的判定值脱节。
    """
    min_len = getattr(settings, "PASSWORD_MIN_LEN", 8)
    labels = {
        "length": f"长度至少 {min_len} 位",
        "upper": "包含大写字母",
        "lower": "包含小写字母",
        "digit": "包含数字",
        "special": "包含特殊字符",
    }
    return [
        labels.get(name, name)
        for name, ok in password_strength(password)["checks"].items()
        if not ok
    ]
