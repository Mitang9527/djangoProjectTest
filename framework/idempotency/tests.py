"""幂等键单测（不依赖外部 Redis）"""
import os
import sys
import unittest

# 让测试能找到项目根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from framework.idempotency.core import (
    set_default_backend, LocalMemoryIdempotencyBackend, idempotent,
    idempotent_context, make_fingerprint,
)
from framework.idempotency.exceptions import IdempotencyConflict, IdempotencyInProgress


class IdempotencyDecoratorTest(unittest.TestCase):

    def setUp(self):
        set_default_backend(LocalMemoryIdempotencyBackend())

    def test_replay(self):
        count = 0

        @idempotent(key_fields=["order_id"], ttl=60)
        def f(order_id):
            nonlocal count
            count += 1
            return {"order_id": order_id, "n": count}

        a = f("O001")
        b = f("O001")
        c = f("O002")

        self.assertEqual(a, b)
        self.assertEqual(a["n"], 1)
        self.assertEqual(c["n"], 2)
        self.assertEqual(count, 2)

    def test_fingerprint_conflict(self):
        @idempotent(key_fields=["order_id"], ttl=60, raise_on_conflict=True)
        def f(order_id, amount):
            return amount

        f("O001", 100)
        with self.assertRaises(IdempotencyConflict):
            f("O001", 200)

    def test_key_func(self):
        count = 0

        @idempotent(key_func=lambda uid, action: f"{uid}:{action}", ttl=60)
        def f(uid, action):
            nonlocal count
            count += 1
            return f"{uid}-{action}-{count}"

        a = f("U1", "login")
        b = f("U1", "login")
        c = f("U1", "logout")

        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_fingerprint_ignores_unknown_keys(self):
        # 两次调用除 ignore_fields 字段外一致 → 应视为相同
        count = 0

        @idempotent(key_fields=["order_id"], ttl=60, ignore_fields=["trace_id"])
        def f(order_id, **kwargs):
            nonlocal count
            count += 1
            return (order_id, count)

        a = f("O001", trace_id="t1")
        b = f("O001", trace_id="t2")  # trace_id 被 ignore
        self.assertEqual(a, b)


class IdempotencyContextTest(unittest.TestCase):

    def setUp(self):
        set_default_backend(LocalMemoryIdempotencyBackend())

    def test_replay_via_context(self):
        seen = []

        def handler(uid):
            with idempotent_context(
                key=f"user:{uid}",
                fingerprint=uid,
                ttl=60,
            ) as ctx:
                if ctx.is_replay:
                    seen.append(("replay", ctx.replayed_response))
                    return ctx.replayed_response
                response = {"uid": uid, "data": [1, 2, 3]}
                ctx.store(response)
                seen.append(("new", response))
                return response

        handler("U1")
        handler("U1")
        handler("U2")

        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[0][0], "new")
        self.assertEqual(seen[1][0], "replay")
        self.assertEqual(seen[2][0], "new")
        self.assertEqual(seen[0][1], seen[1][1])


class FingerprintTest(unittest.TestCase):

    def test_stable(self):
        a = make_fingerprint((1, 2), {"x": 1, "y": 2})
        b = make_fingerprint((1, 2), {"y": 2, "x": 1})  # 顺序无关
        self.assertEqual(a, b)

    def test_key_fields(self):
        a = make_fingerprint(("O1", 100, "U1"), {}, key_fields=["order_id"])
        b = make_fingerprint(("O1", 999, "U2"), {}, key_fields=["order_id"])
        self.assertEqual(a, b)  # 只看 order_id
        c = make_fingerprint(("O2", 100, "U1"), {}, key_fields=["order_id"])
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
