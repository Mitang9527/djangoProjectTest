"""
@circuit_breaker 熔断器
========================

状态机::

                  failure_threshold 连续失败
        ┌──────────────────────────────────────┐
        │                                      ▼
    CLOSED ──────────────────────────────► OPEN
        ▲                                      │
        │ success >= success_threshold         │ recovery_time 到期
        │                                      ▼
        └─────────────── HALF_OPEN ◄──────────┘
                          │
                          │ 任何失败 → OPEN
                          ▼
                        OPEN

可配置项：
- failure_threshold：连续失败多少次进入 OPEN
- success_threshold：HALF_OPEN 状态连续成功多少次回到 CLOSED
- recovery_time：OPEN 持续多久后进入 HALF_OPEN（秒）
- expected_exceptions：哪些异常视为「失败」（其它异常不计数）
"""
from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence, Type, Union

from loguru import logger

from .state_store import StateStore, get_state_store


class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """熔断器开启时调用，直接拒绝"""


@dataclass
class CircuitBreaker:
    """熔断器实例

    Args:
        name: 熔断器名称（业务唯一）
        failure_threshold: 失败阈值
        success_threshold: HALF_OPEN 成功阈值
        recovery_time: OPEN → HALF_OPEN 等待（秒）
        expected_exceptions: 视为失败的异常类型
        store: 状态存储（None 用默认）
        on_state_change: 状态切换回调
    """
    name: str
    failure_threshold: int = 5
    success_threshold: int = 2
    recovery_time: int = 30
    expected_exceptions: Tuple[Type[BaseException], ...] = (Exception,)
    store: Optional[StateStore] = None
    on_state_change: Optional[Callable[[str, CircuitBreakerState, CircuitBreakerState], None]] = None

    def __post_init__(self):
        if isinstance(self.expected_exceptions, type):
            self.expected_exceptions = (self.expected_exceptions,)
        self.store = self.store or get_state_store()
        # 进程内补充：HASH 锁（防 TOCTOU）
        self._local_lock = threading.Lock()
        # 指标
        self.metrics: dict[str, Any] = {
            "total_calls": 0,
            "total_success": 0,
            "total_failure": 0,
            "total_short_circuited": 0,
            "state_transitions": 0,
        }

    # ---------- 状态读写（持久化 + 进程内） ----------
    def _state_key(self) -> str:
        return f"cb:{self.name}:state"

    def _failure_key(self) -> str:
        return f"cb:{self.name}:failures"

    def _success_key(self) -> str:
        return f"cb:{self.name}:successes"

    def _opened_at_key(self) -> str:
        return f"cb:{self.name}:opened_at"

    def get_state(self) -> CircuitBreakerState:
        raw = self.store.get(self._state_key())
        if not raw:
            return CircuitBreakerState.CLOSED
        try:
            return CircuitBreakerState(raw)
        except ValueError:
            return CircuitBreakerState.CLOSED

    def _set_state(self, new_state: CircuitBreakerState):
        old = self.get_state()
        if old == new_state:
            return
        self.store.set(self._state_key(), new_state.value, ttl=max(self.recovery_time * 5, 300))
        self.metrics["state_transitions"] += 1
        logger.info(f"[cb:{self.name}] 状态切换 {old.value} → {new_state.value}")
        if self.on_state_change:
            try:
                self.on_state_change(self.name, old, new_state)
            except Exception:
                pass

    # ---------- 入口判断 ----------
    def allow_request(self) -> bool:
        state = self.get_state()
        if state == CircuitBreakerState.CLOSED:
            return True
        if state == CircuitBreakerState.OPEN:
            opened_at = self.store.get(self._opened_at_key()) or 0
            if time.time() - opened_at >= self.recovery_time:
                self._set_state(CircuitBreakerState.HALF_OPEN)
                self.store.set(self._success_key(), 0, ttl=self.recovery_time * 5)
                return True
            return False
        # HALF_OPEN：放行一个试探
        return True

    # ---------- 调用结果反馈 ----------
    def record_success(self):
        self.metrics["total_success"] += 1
        state = self.get_state()
        if state == CircuitBreakerState.HALF_OPEN:
            n = self.store.incr(self._success_key(), 1, ttl=self.recovery_time * 5)
            if n >= self.success_threshold:
                self._set_state(CircuitBreakerState.CLOSED)
                self.store.delete(self._failure_key())
                self.store.delete(self._success_key())
        elif state == CircuitBreakerState.CLOSED:
            # 成功可以清零失败计数
            self.store.delete(self._failure_key())

    def record_failure(self, exc: BaseException):
        self.metrics["total_failure"] += 1
        state = self.get_state()
        if state == CircuitBreakerState.HALF_OPEN:
            # 任何失败立即回到 OPEN
            self._open()
            return
        n = self.store.incr(self._failure_key(), 1, ttl=max(self.recovery_time * 5, 300))
        if n >= self.failure_threshold:
            self._open()

    def _open(self):
        self.store.set(self._opened_at_key(), time.time(),
                       ttl=max(self.recovery_time * 5, 300))
        self._set_state(CircuitBreakerState.OPEN)

    # ---------- 装饰器桥接 ----------
    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def call(self, func, *args, **kwargs):
        self.metrics["total_calls"] += 1
        with self._local_lock:
            if not self.allow_request():
                self.metrics["total_short_circuited"] += 1
                raise CircuitOpenError(
                    f"circuit breaker '{self.name}' is OPEN"
                )
        try:
            result = func(*args, **kwargs)
        except self.expected_exceptions as e:
            with self._local_lock:
                self.record_failure(e)
            raise
        with self._local_lock:
            self.record_success()
        return result


# 装饰器
def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    success_threshold: int = 2,
    recovery_time: int = 30,
    expected_exceptions: Union[Type[BaseException], Sequence[Type[BaseException]]] = Exception,
    on_state_change: Optional[Callable] = None,
    store: Optional[StateStore] = None,
):
    """熔断器装饰器"""
    if isinstance(expected_exceptions, type):
        expected_exceptions = (expected_exceptions,)

    cb = CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        success_threshold=success_threshold,
        recovery_time=recovery_time,
        expected_exceptions=tuple(expected_exceptions),
        on_state_change=on_state_change,
        store=store,
    )

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return cb.call(func, *args, **kwargs)
        wrapper.circuit_breaker = cb  # 暴露实例便于测试 / 监控
        return wrapper
    return decorator
