"""
随机数据生成工具

功能:
1. 随机整数
2. 随机浮点数
3. 验证码
4. 随机字符串
5. Token
6. UUID
7. 密码生成
"""

import datetime
import random
import secrets
import string
import uuid


def gen_order_no(prefix: str, length: int = 8, date_fmt: str = "%Y%m%d", sep: str = "-") -> str:
    """生成带前缀 + 日期戳 + 随机串的业务单号（统一单号格式，避免各处手写）。

    示例:
        gen_order_no("ORD")                          -> "ORD-20260806-1A2B3C4D"
        gen_order_no("RC", 6, "%Y%m%d%H%M%S", sep="") -> "RC202608061230451A2B3C"
    """
    stamp = datetime.datetime.now().strftime(date_fmt)
    return f"{prefix}{sep}{stamp}{sep}{uuid.uuid4().hex[:length].upper()}"


class RandomGenerator:
    """
    随机生成器
    """

    # 字符池
    LETTERS = string.ascii_letters
    LOWERCASE = string.ascii_lowercase
    UPPERCASE = string.ascii_uppercase
    DIGITS = string.digits

    ALL_CHARS = (
        LETTERS +
        DIGITS
    )


    @staticmethod
    def number(start=1, end=100):
        """
        生成随机整数

        示例:
        1-100之间随机数
        """
        return random.randint(start, end)


    @staticmethod
    def float_number(start=0, end=1, precision=2):
        """
        生成随机浮点数
        """
        value = random.uniform(start, end)

        return round(
            value,
            precision
        )


    @staticmethod
    def code(length=6):
        """
        生成数字验证码

        示例:
        928381
        """

        return ''.join(
            secrets.choice(
                RandomGenerator.DIGITS
            )
            for _ in range(length)
        )


    @staticmethod
    def string(length=16):
        """
        生成随机字符串

        包含:
        - 大小写字母
        - 数字
        """

        return ''.join(
            secrets.choice(
                RandomGenerator.ALL_CHARS
            )
            for _ in range(length)
        )


    @staticmethod
    def lower_string(length=16):
        """
        小写随机字符串
        """

        return ''.join(
            secrets.choice(
                RandomGenerator.LOWERCASE
            )
            for _ in range(length)
        )


    @staticmethod
    def token(length=32):
        """
        生成安全Token

        适合:
        - API Key
        - 临时授权
        - Session
        """

        return secrets.token_hex(
            length
        )


    @staticmethod
    def uuid():
        """
        生成UUID

        示例:
        550e8400-e29b-41d4-a716-446655440000
        """

        return str(
            uuid.uuid4()
        )


    @staticmethod
    def password(length=12):
        """
        生成随机密码

        默认包含:
        - 大写
        - 小写
        - 数字
        - 特殊字符
        """

        chars = (
            string.ascii_letters
            +
            string.digits
            +
            "!@#$%^&*"
        )

        return ''.join(
            secrets.choice(chars)
            for _ in range(length)
        )


    @staticmethod
    def choice(items):
        """
        随机选择一个元素

        示例:
        choice(["a","b","c"])
        """

        return random.choice(items)


    @staticmethod
    def batch(func, count=10, *args, **kwargs):
        """
        批量生成随机数据

        示例:
        batch(RandomGenerator.code,5)
        """

        return [
            func(*args, **kwargs)
            for _ in range(count)
        ]