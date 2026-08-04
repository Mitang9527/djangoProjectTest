# sync-init: skip
"""
业务校验器
==========

零依赖（仅标准库 + DRF）。

- 手机号 / 身份证 / 银行卡 / 邮箱 / URL / IPv4 / IPv6
- 强密码策略
- 业务规则引擎（json 描述）

Examples
--------
>>> from framework.drf.validators import is_valid_chinese_mobile, password_strength

>>> is_valid_chinese_mobile("13800138000")
True
>>> password_strength("P@ssw0rd!23")
{'score': 5, 'level': 'strong'}
"""
from __future__ import annotations

import ipaddress
import re
import string
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union


# ============================================================================
# 1. 单条校验函数
# ============================================================================

_RE_MOBILE_CN = re.compile(r"^1[3-9]\d{9}$")
_RE_ID_CN = re.compile(r"^\d{17}[\dXx]$")
_RE_EMAIL = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)
_RE_URL = re.compile(
    r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE
)
_RE_BANK_CARD = re.compile(r"^\d{13,19}$")


def is_valid_chinese_mobile(value: str) -> bool:
    """中国手机号（11 位，1[3-9] 开头）。"""
    return bool(value) and bool(_RE_MOBILE_CN.match(str(value)))


def is_valid_id_card_cn(value: str) -> bool:
    """中国身份证号（18 位，含校验位）。"""
    if not value or not _RE_ID_CN.match(value):
        return False
    # GB 11643-1999 校验位算法
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_map = "10X98765432"
    try:
        total = sum(int(value[i]) * weights[i] for i in range(17))
    except ValueError:
        return False
    return check_map[total % 11] == value[17].upper()


def is_valid_email(value: str) -> bool:
    return bool(value) and bool(_RE_EMAIL.match(str(value)))


def is_valid_url(value: str) -> bool:
    return bool(value) and bool(_RE_URL.match(str(value)))


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except (ipaddress.AddressValueError, ValueError):
        return False


def is_valid_ipv6(value: str) -> bool:
    try:
        ipaddress.IPv6Address(value)
        return True
    except (ipaddress.AddressValueError, ValueError):
        return False


def is_valid_ip(value: str) -> bool:
    return is_valid_ipv4(value) or is_valid_ipv6(value)


def is_valid_bank_card(value: str) -> bool:
    """银行卡 Luhn 校验。"""
    if not value or not _RE_BANK_CARD.match(value):
        return False
    digits = [int(d) for d in value]
    checksum = 0
    for i, d in enumerate(reversed(digits[:-1])):
        d = d * 2 if i % 2 == 0 else d
        checksum += d - 9 if d > 9 else d
    return (checksum + digits[-1]) % 10 == 0


def is_valid_chinese_name(value: str) -> bool:
    """中文姓名（2-20 个汉字或 · 间隔的少数民族名）。"""
    return bool(value) and bool(
        re.match(r"^[\u4e00-\u9fa5·]{2,20}$", str(value))
    )


# ============================================================================
# 2. 密码强度
# ============================================================================

@dataclass
class PasswordStrengthResult:
    score: int            # 0-5
    level: str            # very_weak / weak / medium / strong / very_strong
    suggestions: List[str]


_RULES = [
    (r"[a-z]", "小写字母"),
    (r"[A-Z]", "大写字母"),
    (r"\d", "数字"),
    (r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\/'`~;]", "特殊字符"),
]


def password_strength(
    value: str,
    *,
    min_length: int = 8,
    max_length: int = 128,
) -> PasswordStrengthResult:
    """
    密码强度评分（0-5），含改进建议。
    """
    suggestions: List[str] = []
    if not value:
        return PasswordStrengthResult(0, "very_weak", ["密码不能为空"])
    if len(value) < min_length:
        suggestions.append(f"长度至少 {min_length} 位")
    if len(value) > max_length:
        suggestions.append(f"长度不超过 {max_length} 位")

    score = 0
    if len(value) >= min_length:
        score += 1
    if any(re.search(p, value) for p, _ in _RULES):
        score += 1
    # 同时满足 3 类
    rule_hits = sum(1 for p, _ in _RULES if re.search(p, value))
    if rule_hits >= 2:
        score += 1
    if rule_hits >= 3:
        score += 1
    if rule_hits >= 4 and len(value) >= 12:
        score += 1

    # 缺啥补啥
    for p, label in _RULES:
        if not re.search(p, value):
            suggestions.append(f"建议包含{label}")

    # 常见弱密码
    if value.lower() in {"password", "12345678", "qwerty", "abc123", "iloveyou"}:
        score = min(score, 1)
        suggestions.append("不要使用常见弱密码")

    levels = ["very_weak", "weak", "medium", "strong", "very_strong", "very_strong"]
    return PasswordStrengthResult(
        score=min(score, 5),
        level=levels[min(score, 5)],
        suggestions=suggestions,
    )


# ============================================================================
# 3. DRF Field 包装
# ============================================================================

class ChineseMobileField:
    """DRF 字段包装：用 ``serializers.CharField(validators=[validate_chinese_mobile])`` 即可。"""


def validate_chinese_mobile(value: str) -> str:
    if not is_valid_chinese_mobile(value):
        from rest_framework.exceptions import ValidationError
        raise ValidationError(f"手机号格式不正确: {value}")
    return value


def validate_id_card_cn(value: str) -> str:
    if not is_valid_id_card_cn(value):
        from rest_framework.exceptions import ValidationError
        raise ValidationError("身份证号格式不正确")
    return value


def validate_email(value: str) -> str:
    if not is_valid_email(value):
        from rest_framework.exceptions import ValidationError
        raise ValidationError(f"邮箱格式不正确: {value}")
    return value


def validate_url(value: str) -> str:
    if not is_valid_url(value):
        from rest_framework.exceptions import ValidationError
        raise ValidationError(f"URL 格式不正确: {value}")
    return value


def validate_ip(value: str) -> str:
    if not is_valid_ip(value):
        from rest_framework.exceptions import ValidationError
        raise ValidationError(f"IP 地址格式不正确: {value}")
    return value


def validate_bank_card(value: str) -> str:
    if not is_valid_bank_card(value):
        from rest_framework.exceptions import ValidationError
        raise ValidationError("银行卡号格式不正确")
    return value


def validate_password(
    value: str,
    *,
    min_length: int = 8,
    require_strong: bool = False,
) -> str:
    """
    DRF validator 风格的密码校验。

    Parameters
    ----------
    require_strong : bool
        是否要求 strength.level >= strong（score >= 4）
    """
    result = password_strength(value, min_length=min_length)
    if require_strong and result.score < 4:
        from rest_framework.exceptions import ValidationError
        raise ValidationError(
            {"password": "密码强度不足", "suggestions": result.suggestions}
        )
    if result.score < 2:
        from rest_framework.exceptions import ValidationError
        raise ValidationError(
            {"password": "密码太弱", "suggestions": result.suggestions}
        )
    return value


# ============================================================================
# 4. 业务规则引擎
# ============================================================================

@dataclass
class RuleResult:
    passed: bool
    message: str = ""
    actual: Any = None
    expected: Any = None


class RuleEngine:
    """
    极简规则引擎：用 dict 描述规则列表。

    支持的操作符
    ------------
    ``eq / ne / gt / gte / lt / lte / in / not_in / contains / regex / between / is_null / is_not_null``

    Examples
    --------
    >>> engine = RuleEngine(rules=[
    ...     {"field": "age", "op": "gte", "value": 18, "message": "必须年满 18"},
    ...     {"field": "country", "op": "in", "value": ["CN", "US"]},
    ... ])
    >>> results = engine.validate({"age": 20, "country": "CN"})
    >>> all(r.passed for r in results)
    True
    """

    OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {}

    def __init__(self, rules: List[Dict[str, Any]]):
        self.rules = rules

    @classmethod
    def register(cls, name: str, fn: Callable):
        cls.OPERATORS[name] = fn

    def validate(self, data: Dict[str, Any]) -> List[RuleResult]:
        results = []
        for rule in self.rules:
            field = rule["field"]
            op = rule["op"]
            expected = rule.get("value")
            message = rule.get("message", f"字段 {field} 校验失败: {op} {expected}")
            actual = self._get_field(data, field)
            fn = self.OPERATORS.get(op)
            if fn is None:
                results.append(RuleResult(False, f"未知操作符: {op}"))
                continue
            try:
                passed = bool(fn(actual, expected))
            except Exception as e:
                passed = False
                message = f"{message} (error: {e})"
            results.append(RuleResult(passed, message, actual, expected))
        return results

    def is_valid(self, data: Dict[str, Any]) -> bool:
        return all(r.passed for r in self.validate(data))

    @staticmethod
    def _get_field(data: Dict[str, Any], path: str) -> Any:
        """支持点路径：``"user.profile.age"``。"""
        cur: Any = data
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur


# 注册默认操作符
def _op_eq(a, b): return a == b
def _op_ne(a, b): return a != b
def _op_gt(a, b): return a is not None and a > b
def _op_gte(a, b): return a is not None and a >= b
def _op_lt(a, b): return a is not None and a < b
def _op_lte(a, b): return a is not None and a <= b
def _op_in(a, b):
    """a 是标量：a in b；a 是 list/tuple：任一元素 in b。"""
    if isinstance(a, (list, tuple, set)):
        return any(x in (b or []) for x in a)
    return a in (b or [])
def _op_not_in(a, b):
    if isinstance(a, (list, tuple, set)):
        return not any(x in (b or []) for x in a)
    return a not in (b or [])
def _op_contains(a, b): return b in (a or "")
def _op_regex(a, b): return a is not None and re.search(b, str(a)) is not None
def _op_between(a, b):
    if a is None or not isinstance(b, (list, tuple)) or len(b) != 2:
        return False
    lo, hi = b
    return lo <= a <= hi
def _op_is_null(a, b): return a is None
def _op_is_not_null(a, b): return a is not None


for _name, _fn in list(locals().items()):
    if _name.startswith("_op_"):
        RuleEngine.register(_name[4:], _fn)
