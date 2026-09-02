"""
@bulkhead 隔离舱
================

限制对某个资源的并发调用数。

- **信号量模式**：max_concurrent 个槽位，满了立即抛 BulkheadFullError（或等待 max_wait）
- **线程池模式**：max_concurrent 个线程长驻，超出排队
"""
from __future__ import annotations

import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from loguru import logger

from .state_store import StateStore, get_state_store


class BulkheadFullError(Exception):
    """隔离舱已满"""


class Bulkhead:
    """信号量式隔离舱

    Args:
        name: 隔离舱名
        max_concurrent: 最大并发
        max_wait: 等待槽位的最长时间
        store: 状态存储（None 用默认）
    """

    def __init__(
        self,
        name: str,
        max_concurrent: int = 10,
        max_wait: float = 0.0,
        store: Optional[StateStore] = None,
    ):
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_wait = max_wait
        self.store = store or get_state_store()
        # 进程内 semaphore（保证本地原子性）
        self._sem = threading.BoundedSemaphore(max_concurrent)
        self.metrics = {
            "calls_total": 0,
            "calls_rejected": 0,
            "calls_completed": 0,
        }

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """尝试获取槽位"""
        timeout = timeout if timeout is not None else self.max_wait
        self.metrics["calls_total"] += 1
        # BoundedSemaphore.acquire 不允许同时传 timeout 和 blocking=False
        if timeout > 0:
            got = self._sem.acquire(timeout=timeout, blocking=True)
        else:
            got = self._sem.acquire(blocking=False)
        if not got:
            self.metrics["calls_rejected"] += 1
            return False
        return True

    def release(self):
        try:
            self._sem.release()
        except ValueError:
            pass

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        wrapper.bulkhead = self
        return wrapper

    def call(self, func, *args, **kwargs):
        if not self.acquire():
            raise BulkheadFullError(
                f"bulkhead '{self.name}' full (max={self.max_concurrent})"
            )
        try:
            result = func(*args, **kwargs)
            self.metrics["calls_completed"] += 1
            return result
        finally:
            self.release()


def bulkhead(
    name: str,
    max_concurrent: int = 10,
    max_wait: float = 0.0,
    store: Optional[StateStore] = None,
):
    """隔离舱装饰器"""
    bh = Bulkhead(
        name=name, max_concurrent=max_concurrent, max_wait=max_wait, store=store
    )

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return bh.call(func, *args, **kwargs)
        wrapper.bulkhead = bh
        return wrapper
    return decorator
