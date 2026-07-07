"""
分布式锁工具包
==============

提供 RedisLock（单节点）与 RedLock（多节点）实现，
支持重入、自动续期、公平锁等高级特性。

快速开始
--------

**基础用法**::

    from utils.locks import RedisLock

    with RedisLock("order:123:pay", ttl=30):
        do_payment()
    # 自动释放

**手动控制**::

    lock = RedisLock("inventory:sku-001", ttl=10)
    if lock.acquire(blocking=False):
        try:
            deduct_stock()
        finally:
            lock.release()

**自动续期（看门狗）**::

    # 长任务执行期间，每 ttl/3 自动续期一次
    with RedisLock("long_task", ttl=30, auto_renewal=True):
        run_long_task()

**作为装饰器**::

    from utils.locks import locked

    @locked(key=lambda order_id: f"order:{order_id}:pay", ttl=30)
    def pay(order_id):
        ...
"""
from .core import (
    LockBackend,
    LockAcquireError,
    LockReleaseError,
    LockTimeoutError,
    LockState,
    RedisLock,
    RedLock,
    locked,
    get_default_backend,
    set_default_backend,
)

__all__ = [
    "LockBackend",
    "LockAcquireError",
    "LockReleaseError",
    "LockTimeoutError",
    "LockState",
    "RedisLock",
    "RedLock",
    "locked",
    "get_default_backend",
    "set_default_backend",
]
