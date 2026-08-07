"""
容错工具集使用示例
==================
"""
from __future__ import annotations

import random
import time


# ============================================================
# 示例 1：重试
# ============================================================
def example_1_retry():
    from framework.reliability import retry

    attempt_count = 0

    @retry(
        max_attempts=4,
        backoff="exponential",
        initial_delay=0.05,
        max_delay=1.0,
        jitter=True,
        retry_on=(ConnectionError,),
    )
    def fetch_data():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ConnectionError("network down")
        return {"data": "ok", "attempt": attempt_count}

    result = fetch_data()
    print(f"[示例1] 重试成功: {result}")


# ============================================================
# 示例 2：熔断器
# ============================================================
def example_2_circuit_breaker():
    from framework.reliability import circuit_breaker, CircuitOpenError
    from framework.reliability.state_store import set_state_store, InMemoryStateStore

    set_state_store(InMemoryStateStore())

    call_count = 0

    @circuit_breaker(
        name="flaky_api",
        failure_threshold=3,
        success_threshold=1,
        recovery_time=2,
    )
    def flaky_call():
        nonlocal call_count
        call_count += 1
        if call_count <= 4:  # 4 次失败
            raise ConnectionError(f"call {call_count} failed")
        return "success"

    # 4 次失败 → 第 3 次后熔断打开
    for i in range(4):
        try:
            r = flaky_call()
            print(f"  call {i + 1}: {r}")
        except (ConnectionError, CircuitOpenError) as e:
            print(f"  call {i + 1}: {type(e).__name__}: {e!r}")

    # 等待恢复
    print("  等待熔断恢复...")
    time.sleep(2.1)

    # 试探一次
    try:
        r = flaky_call()
        print(f"  恢复后调用: {r}")
    except Exception as e:
        print(f"  恢复后仍失败: {e!r}")


# ============================================================
# 示例 3：隔离舱
# ============================================================
def example_3_bulkhead():
    from framework.reliability import bulkhead, BulkheadFullError
    import threading

    active = 0
    peak = 0
    lock = threading.Lock()

    @bulkhead(name="slow_api", max_concurrent=3, max_wait=0)
    def slow():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.2)
        finally:
            with lock:
                active -= 1
        return "done"

    results = []
    def worker():
        try:
            slow()
            results.append("ok")
        except BulkheadFullError:
            results.append("rejected")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    print(f"[示例3] 10 个并发，最大同时活跃={peak}，"
          f"成功={results.count('ok')}，拒绝={results.count('rejected')}")


# ============================================================
# 示例 4：降级
# ============================================================
def example_4_fallback():
    from framework.reliability import fallback

    @fallback(default=lambda uid: {"user_id": uid, "name": "Anonymous", "from": "cache"})
    def get_user_profile(uid: str):
        raise ConnectionError("user service down")

    profile = get_user_profile("U001")
    print(f"[示例4] 降级响应: {profile}")


# ============================================================
# 示例 5：四件套组合
# ============================================================
def example_5_combo():
    """生产典型场景：调用外部支付网关"""
    from framework.reliability import retry, circuit_breaker, bulkhead, fallback

    call_count = 0

    @fallback(default={"status": "queued", "reason": "service unavailable"})
    @retry(max_attempts=3, backoff="exponential", initial_delay=0.05,
           retry_on=(ConnectionError,))
    @circuit_breaker(name="payment_gw", failure_threshold=5, recovery_time=10)
    @bulkhead(name="payment_gw", max_concurrent=10, max_wait=1.0)
    def charge(amount: int, card_no: str):
        nonlocal call_count
        call_count += 1
        # 50% 失败率
        if random.random() < 0.5:
            raise ConnectionError("network blip")
        return {"amount": amount, "card": card_no[-4:], "status": "charged"}

    results = [charge(100, "4111111111111111") for _ in range(6)]
    print(f"[示例5] 6 次调用，业务执行总次数={call_count}, "
          f"结果: {[r['status'] for r in results]}")


if __name__ == "__main__":
    random.seed(42)
    example_1_retry()
    print()
    example_2_circuit_breaker()
    print()
    example_3_bulkhead()
    print()
    example_4_fallback()
    print()
    example_5_combo()
    print("\n所有容错示例执行完毕")
