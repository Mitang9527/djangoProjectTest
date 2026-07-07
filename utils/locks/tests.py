"""分布式锁单测"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.locks.core import (
    set_default_backend, LocalMemoryLockBackend,
    RedisLock, LockAcquireError, LockTimeoutError, locked,
)


class RedisLockTest(unittest.TestCase):

    def setUp(self):
        set_default_backend(LocalMemoryLockBackend())

    def test_acquire_release(self):
        lock = RedisLock("t1", ttl=5)
        lock.acquire()
        self.assertTrue(lock.is_held())
        lock.release()
        self.assertFalse(lock.is_held())

    def test_context_manager(self):
        with RedisLock("t2", ttl=5) as lock:
            self.assertTrue(lock.is_held())
        self.assertFalse(lock.is_held())

    def test_mutual_exclusion(self):
        order = []

        def worker(name, hold):
            with RedisLock("mutex", ttl=5, wait=2):
                order.append(f"{name}-enter")
                time.sleep(hold)
                order.append(f"{name}-exit")

        t1 = threading.Thread(target=worker, args=("A", 0.1))
        t2 = threading.Thread(target=worker, args=("B", 0.05))
        t1.start(); time.sleep(0.02); t2.start()
        t1.join(); t2.join()

        # 必须是 A-enter, A-exit, B-enter, B-exit 串行
        self.assertEqual(order, ["A-enter", "A-exit", "B-enter", "B-exit"])

    def test_non_blocking(self):
        RedisLock("a", ttl=5).acquire()
        lock2 = RedisLock("a", ttl=5)
        self.assertFalse(lock2.try_acquire())
        with self.assertRaises(LockAcquireError):
            lock2.acquire(blocking=False)

    def test_timeout(self):
        RedisLock("b", ttl=5).acquire()
        lock2 = RedisLock("b", ttl=5, wait=0.1)
        with self.assertRaises(LockTimeoutError):
            lock2.acquire()

    def test_reentrant(self):
        lock = RedisLock("rec", ttl=5, reentrant=True)
        with lock:
            with lock:  # 同一 owner 二次进入
                self.assertTrue(lock.is_held())
            self.assertTrue(lock.is_held())
        self.assertFalse(lock.is_held())

    def test_renew(self):
        lock = RedisLock("r", ttl=2)
        lock.acquire()
        self.assertTrue(lock.renew(ttl=5))
        lock.release()

    def test_locked_decorator(self):
        seen = []

        @locked(key="order:{order_id}:pay", ttl=5, wait=2)
        def pay(order_id):
            seen.append(order_id)
            return f"paid-{order_id}"

        a = pay("O1")
        b = pay("O1")
        self.assertEqual(a, b)
        # 同一 key 串行执行两次
        self.assertEqual(seen, ["O1", "O1"])


if __name__ == "__main__":
    unittest.main()
