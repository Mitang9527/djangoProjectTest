"""
@fallback 降级装饰器
====================

当被装饰函数抛出指定异常时，返回兜底值或调用备用函数。

兜底值可以是：
- 字面量（lambda 表达式或常量）
- callable（接收相同的 *args, **kwargs）
- None（直接返回 None）
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Optional, Sequence, Type, Union

from loguru import logger


def fallback(
    default: Any = None,
    raise_on: Union[Type[BaseException], Sequence[Type[BaseException]]] = Exception,
    log: bool = True,
):
    """降级装饰器

    Args:
        default: 兜底值（callable 或常量）
        raise_on: 触发降级的异常类型
        log: 是否记录降级日志

    Examples::

        @fallback(default=lambda uid: [])
        def get_recommendations(uid):
            return call_recommend_service(uid)

        @fallback(default={"status": "down"})
        def health_check():
            return call_external_health()
    """
    if isinstance(raise_on, type):
        raise_on = (raise_on,)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except tuple(raise_on) as e:
                if log:
                    logger.warning(
                        f"[fallback] '{func.__name__}' 失败 ({e!r})，使用兜底"
                    )
                if callable(default):
                    try:
                        return default(*args, **kwargs)
                    except Exception as inner_e:
                        logger.error(
                            f"[fallback] '{func.__name__}' 兜底函数也失败: {inner_e!r}"
                        )
                        return None
                return default
        return wrapper
    return decorator
