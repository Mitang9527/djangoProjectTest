"""
@retry 装饰器
=============

支持：
- 指数 / 线性 / 常数退避
- 抖动（防雷鸣群）
- 异常白名单 / 黑名单
- 最多重试次数 / 最长总耗时
- 重试回调（用于埋点）
"""
from __future__ import annotations

import functools
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple, Type, Union

from loguru import logger


@dataclass
class RetryPolicy:
    """重试策略"""
    max_attempts: int = 3
    backoff: str = "exponential"      # "linear" | "exponential" | "constant"
    initial_delay: float = 0.1        # 首次重试延迟（秒）
    max_delay: float = 30.0           # 单次重试最大延迟
    multiplier: float = 2.0           # 指数退避乘数
    jitter: bool = True               # 抖动
    retry_on: Tuple[Type[BaseException], ...] = (Exception,)
    give_up_on: Tuple[Type[BaseException], ...] = ()
    max_total_time: Optional[float] = None  # 最长总耗时（秒）
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None  # (attempt, exc, delay)

    def compute_delay(self, attempt: int) -> float:
        """attempt 从 1 开始"""
        if self.backoff == "constant":
            delay = self.initial_delay
        elif self.backoff == "linear":
            delay = self.initial_delay * attempt
        elif self.backoff == "exponential":
            delay = self.initial_delay * (self.multiplier ** (attempt - 1))
        else:
            delay = self.initial_delay

        delay = min(delay, self.max_delay)
        if self.jitter:
            # Full jitter: random between 0 and delay
            delay = random.uniform(0, delay)
        return max(0, delay)


def retry(
    max_attempts: int = 3,
    backoff: str = "exponential",
    initial_delay: float = 0.1,
    max_delay: float = 30.0,
    multiplier: float = 2.0,
    jitter: bool = True,
    retry_on: Union[Type[BaseException], Sequence[Type[BaseException]]] = Exception,
    give_up_on: Union[Type[BaseException], Sequence[Type[BaseException]]] = (),
    max_total_time: Optional[float] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
):
    """重试装饰器

    Args:
        max_attempts: 最大尝试次数（含首次）
        backoff: 退避策略
        initial_delay: 首次重试延迟
        max_delay: 单次重试最大延迟
        multiplier: 指数退避乘数
        jitter: 是否抖动
        retry_on: 触发重试的异常类型
        give_up_on: 立即放弃的异常类型（不重试）
        max_total_time: 整体超时
        on_retry: 重试回调 (attempt, exc, delay)

    Examples::

        @retry(max_attempts=5, backoff="exponential",
               retry_on=(requests.RequestException, TimeoutError))
        def fetch():
            ...
    """
    if isinstance(retry_on, type):
        retry_on = (retry_on,)
    if isinstance(give_up_on, type):
        give_up_on = (give_up_on,)

    policy = RetryPolicy(
        max_attempts=max_attempts,
        backoff=backoff,
        initial_delay=initial_delay,
        max_delay=max_delay,
        multiplier=multiplier,
        jitter=jitter,
        retry_on=tuple(retry_on),
        give_up_on=tuple(give_up_on),
        max_total_time=max_total_time,
        on_retry=on_retry,
    )

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return _do_retry(func, args, kwargs, policy)
        return wrapper
    return decorator


def _do_retry(func, args, kwargs, policy: RetryPolicy):
    start = time.time()
    last_exc: Optional[BaseException] = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except policy.give_up_on as e:
            # 立即放弃
            raise
        except policy.retry_on as e:
            last_exc = e
            if attempt >= policy.max_attempts:
                logger.warning(
                    f"[retry] '{func.__name__}' 已达最大尝试次数 {policy.max_attempts}：{e!r}"
                )
                raise

            # 检查总时间
            elapsed = time.time() - start
            if policy.max_total_time and elapsed >= policy.max_total_time:
                logger.warning(
                    f"[retry] '{func.__name__}' 超出总时长 {policy.max_total_time}s：{e!r}"
                )
                raise

            delay = policy.compute_delay(attempt)
            if policy.on_retry:
                try:
                    policy.on_retry(attempt, e, delay)
                except Exception:
                    pass
            else:
                logger.info(
                    f"[retry] '{func.__name__}' 第 {attempt}/{policy.max_attempts - 1} 次失败，"
                    f"等待 {delay:.2f}s 后重试: {e!r}"
                )
            time.sleep(delay)

    # 不应到达此处
    if last_exc:
        raise last_exc
