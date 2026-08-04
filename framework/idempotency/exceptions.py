"""幂等相关异常"""


class IdempotencyError(Exception):
    """幂等基类异常"""


class IdempotencyConflict(IdempotencyError):
    """同样的 key，但请求体不同"""


class IdempotencyInProgress(IdempotencyError):
    """另一个 worker 正在处理同一个 key"""
