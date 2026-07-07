"""
容错工具包
==========

提供 resilience4j 风格的容错原语：

- **@retry**：失败重试（指数退避 + 抖动 + 异常白/黑名单）
- **@circuit_breaker**：熔断器（CLOSED → OPEN → HALF_OPEN）
- **@bulkhead**：隔离舱（限制并发）
- **@fallback**：失败兜底（返回默认值或调用备用函数）

四件套可任意组合使用。状态共享：熔断器按 name 全进程唯一，可注入到 metrics。

快速开始
--------

**重试**::

    from utils.reliability import retry

    @retry(max_attempts=3, backoff="exponential", jitter=True,
           retry_on=(requests.RequestException,))
    def call_third_party():
        return requests.get("https://api.example.com/data")


**熔断器**::

    from utils.reliability import circuit_breaker

    @circuit_breaker(name="payment_api", failure_threshold=5,
                     recovery_time=30, expected_exceptions=(PaymentError,))
    def charge_credit_card(order):
        ...


**隔离舱**::

    from utils.reliability import bulkhead

    @bulkhead(name="email_send", max_concurrent=20, max_wait=5.0)
    def send_email(to, subject, body):
        ...


**降级**::

    from utils.reliability import fallback

    @fallback(default=lambda *a, **kw: {"cached": True, "data": []})
    def get_recommendations(user_id):
        ...


**组合使用**::

    from utils.reliability import retry, circuit_breaker, fallback

    @fallback(default=lambda uid: [])
    @retry(max_attempts=3)
    @circuit_breaker(name="inventory", failure_threshold=10, recovery_time=60)
    def get_inventory(uid):
        ...
"""
from .retry import retry, RetryPolicy
from .circuit_breaker import (
    circuit_breaker,
    CircuitBreaker,
    CircuitBreakerState,
    CircuitOpenError,
)
from .bulkhead import bulkhead, Bulkhead, BulkheadFullError
from .fallback import fallback
from .state_store import get_state_store, set_state_store, StateStore, InMemoryStateStore

__all__ = [
    "retry", "RetryPolicy",
    "circuit_breaker", "CircuitBreaker", "CircuitBreakerState", "CircuitOpenError",
    "bulkhead", "Bulkhead", "BulkheadFullError",
    "fallback",
    "get_state_store", "set_state_store", "StateStore", "InMemoryStateStore",
]
