"""
分布式锁使用示例
================
"""
from __future__ import annotations

import time

# ============================================================
# 示例 1：库存扣减
# ============================================================
def example_1_inventory():
    """多 worker 并发扣库存：保证只扣一次"""
    from framework.locks import RedisLock

    inventory = {"sku-001": 10}

    def deduct(sku: str, qty: int):
        with RedisLock(f"inventory:{sku}", ttl=5, wait=3):
            if inventory.get(sku, 0) < qty:
                raise ValueError(f"库存不足: {sku}")
            inventory[sku] -= qty
            return inventory[sku]

    # 模拟并发
    import threading
    results = []
    def worker():
        try:
            r = deduct("sku-001", 1)
            results.append(r)
        except Exception as e:
            results.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(15)]
    for t in threads: t.start()
    for t in threads: t.join()

    print(f"[示例1] 库存最终: {inventory}, 成功次数: "
          f"{sum(1 for r in results if isinstance(r, int))}")


# ============================================================
# 示例 2：装饰器 - 支付
# ============================================================
def example_2_decorator():
    from framework.locks import locked
    from framework.locks.core import set_default_backend, LocalMemoryLockBackend

    set_default_backend(LocalMemoryLockBackend())

    pay_count = 0

    @locked(key=lambda order_id, amount: f"order:{order_id}:pay", ttl=10, wait=2)
    def pay(order_id: str, amount: int):
        nonlocal pay_count
        pay_count += 1
        time.sleep(0.1)  # 模拟支付耗时
        return {"order_id": order_id, "amount": amount, "status": "paid"}

    pay("O001", 100)
    pay("O001", 100)  # 同一订单 → 应被锁住，等第一次释放后串行执行
    print(f"[示例2] 两次支付调用，实际执行业务 {pay_count} 次（串行）")


# ============================================================
# 示例 3：看门狗（长任务）
# ============================================================
def example_3_watchdog():
    """长任务：执行 35s，但锁 ttl=10s，看门狗自动续期"""
    from framework.locks import RedisLock
    from framework.locks.core import set_default_backend, LocalMemoryLockBackend

    set_default_backend(LocalMemoryLockBackend())

    lock = RedisLock("long_task", ttl=3, auto_renewal=True)
    lock.acquire()
    print(f"[示例3] 锁已获取，owner={lock.owner[:20]}...")

    # 模拟长任务
    for i in range(3):
        time.sleep(2)
        renewed = lock.renew()
        print(f"  t+{(i + 1) * 2}s 续期: {renewed}")

    lock.release()
    print(f"[示例3] 锁已释放")


# ============================================================
# 示例 4：公平锁 / 高级用法
# ============================================================
def example_4_advanced():
    """手动控制 + 重入"""
    from framework.locks import RedisLock
    from framework.locks.core import set_default_backend, LocalMemoryLockBackend

    set_default_backend(LocalMemoryLockBackend())

    lock = RedisLock("recursion_lock", ttl=10, reentrant=True)

    def recursive(n: int):
        with lock:  # 第二次进入不会死锁（重入）
            if n <= 0:
                return "done"
            return recursive(n - 1)

    result = recursive(5)
    print(f"[示例4] 重入递归结果: {result}")


if __name__ == "__main__":
    example_1_inventory()
    example_2_decorator()
    example_3_watchdog()
    example_4_advanced()
    print("\n所有锁示例执行完毕")
