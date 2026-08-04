"""
API 签名相关异常
"""


class SignatureError(Exception):
    """签名验证基础异常"""
    pass


class InvalidSignatureError(SignatureError):
    """签名无效"""
    pass


class SignatureExpiredError(SignatureError):
    """签名已过期"""
    pass


class NonceUsedError(SignatureError):
    """nonce 已被使用"""
    pass


class MissingHeaderError(SignatureError):
    """缺少必要的请求头"""
    pass
