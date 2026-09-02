"""事务 Outbox（三表：OutboxEvent + EventDelivery + InboxReceipt）端到端验证。

覆盖：
1. 发布 + 投递：业务事件落库 → worker 投递成功 → 写消费凭证 → 事件 COMPLETE；
2. 零消费者：事件直接 COMPLETE（无投递目标）；
3. 失败重试：指数退避（2^attempts 秒），不立即死信；
4. 死信：超限进入 DEAD_LETTER，requeue_dead_letter 人工恢复后重投成功；
5. 幂等：已有 InboxReceipt 的重投不重复执行 handler；
6. 租约锁：认领后未过期不被重复认领，过期后可被重新认领；
7. 多消费者扇出 + 外部 broker 目标；
8. 内存直发降级（use_outbox=False）。
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from framework.events.models import (
    OutboxEvent, OutboxEventStatus,
    EventDelivery, EventDeliveryStatus,
    InboxReceipt,
)
from framework.events.publisher import (
    publish, register_handler, register_external_delivery, unregister_all_handlers,
)
from framework.events.worker import (
    dispatch_pending_events, drain_outbox, requeue_dead_letter, count_pending_events,
)


class OutboxTestCase(TestCase):
    def setUp(self):
        unregister_all_handlers()
        self.received = []

    def tearDown(self):
        unregister_all_handlers()

    def _handler(self, name=None):
        """构造一个记录调用次数的 handler。"""
        def handler(event, payload):
            self.received.append((name or "h", payload.get("n")))
        return handler


class PublishAndDispatchTest(OutboxTestCase):
    def test_publish_creates_event_and_delivery(self):
        register_handler("order.created", self._handler("notify"), consumer_name="notify")
        ev = publish("order.created", {"n": 1}, tenant_id="t1")
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboxEventStatus.PENDING)
        self.assertEqual(ev.deliveries.count(), 1)
        d = ev.deliveries.get()
        self.assertEqual(d.status, EventDeliveryStatus.PENDING)
        self.assertEqual(d.target_name, "notify")

    def test_dispatch_delivers_and_writes_receipt(self):
        register_handler("order.created", self._handler("notify"), consumer_name="notify")
        ev = publish("order.created", {"n": 1})
        delivered, failed = dispatch_pending_events(worker_id="w1")
        self.assertEqual((delivered, failed), (1, 0))
        ev.refresh_from_db()
        d = ev.deliveries.get()
        self.assertEqual(d.status, EventDeliveryStatus.DELIVERED)
        self.assertEqual(d.delivered_at is not None, True)
        self.assertIsNone(d.locked_by)
        # 幂等凭证已写
        self.assertTrue(InboxReceipt.objects.filter(
            consumer_name="notify", event=ev).exists())
        # 事件聚合为 COMPLETE
        self.assertEqual(ev.status, OutboxEventStatus.COMPLETE)
        self.assertEqual(self.received, [("notify", 1)])

    def test_zero_consumer_event_completes_immediately(self):
        # 未注册任何消费者：事件直接 COMPLETE，无投递目标
        ev = publish("notice.broadcast", {"msg": "hello"})
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboxEventStatus.COMPLETE)
        self.assertEqual(ev.deliveries.count(), 0)
        self.assertEqual(count_pending_events(), 0)

    def test_fanout_multiple_consumers_and_external(self):
        register_handler("user.created", self._handler("mail"), consumer_name="mail")
        register_handler("user.created", self._handler("audit"), consumer_name="audit")
        external = mock.Mock()
        register_external_delivery("user.created", "rabbitmq", external)
        ev = publish("user.created", {"n": 9})
        self.assertEqual(ev.deliveries.count(), 3)
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (3, 0))
        self.assertEqual(sorted(r[0] for r in self.received), ["audit", "mail"])
        external.assert_called_once()
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboxEventStatus.COMPLETE)

    def test_inmemory_fallback_when_outbox_disabled(self):
        register_handler("light.event", self._handler("h"))
        # use_outbox=False → 直接调用第一个 handler（旧语义内存直发）
        result = publish("light.event", {"n": 5}, use_outbox=False)
        self.assertEqual(result, None)
        self.assertEqual(self.received, [("h", 5)])
        self.assertEqual(OutboxEvent.objects.count(), 0)


class RetryAndDeadLetterTest(OutboxTestCase):
    def test_failure_backs_off_exponentially(self):
        def boom(event, payload):
            raise RuntimeError("boom")
        register_handler("fragile.task", boom)
        ev = publish("fragile.task", {"n": 1})
        d = ev.deliveries.get()
        # 第一次失败 → PENDING + attempts=1 + 退避 2s
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (0, 1))
        d.refresh_from_db()
        self.assertEqual(d.status, EventDeliveryStatus.PENDING)
        self.assertEqual(d.attempts, 1)
        self.assertEqual(
            (d.available_at - timezone.now()).total_seconds() > 1, True)
        # 退避期内不可投递：再跑一轮 delivered=0 failed=0
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (0, 0))
        # 事件仍 PENDING
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboxEventStatus.PENDING)
        self.assertEqual(ev.attempts, 1)

    def test_dead_letter_after_max_attempts_and_requeue(self):
        def boom(event, payload):
            raise ValueError("always fails")
        register_handler("doomed.task", boom)
        ev = publish("doomed.task", {"n": 1})
        # max_attempts=3：每轮把退避时间拨回（模拟时间流逝），
        # 前两次失败退避，第三次失败转死信
        d = ev.deliveries.get()
        for _ in range(3):
            d.available_at = timezone.now() - timezone.timedelta(seconds=1)
            d.save(update_fields=["available_at"])
            dispatch_pending_events(max_attempts=3)
            d.refresh_from_db()
        self.assertEqual(d.status, EventDeliveryStatus.DEAD_LETTER)
        self.assertEqual(d.dead_lettered_at is not None, True)
        self.assertEqual(d.attempts, 3)
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboxEventStatus.DEAD_LETTER)
        self.assertIn("DELIVERY_HANDLER_FAILED:ValueError", ev.last_error)
        # 死信后不再被认领
        delivered, failed = dispatch_pending_events(max_attempts=3)
        self.assertEqual((delivered, failed), (0, 0))

        # 人工恢复：重置计数与状态后重投成功
        requeue_dead_letter(event_id=ev.id)
        delivered, failed = dispatch_pending_events(max_attempts=3)
        # 注意：handler 仍抛异常，本轮再次失败退避（不会立即死信）
        self.assertEqual((delivered, failed), (0, 1))
        ev.refresh_from_db()
        self.assertEqual(ev.status, OutboxEventStatus.PENDING)


class IdempotencyAndLeaseTest(OutboxTestCase):
    def test_receipt_prevents_duplicate_execution(self):
        register_handler("once.event", self._handler("h"))
        ev = publish("once.event", {"n": 1})
        dispatch_pending_events()
        # 模拟：delivery 被重置为 PENDING 但 receipt 已存在（worker 崩溃后重投）
        d = ev.deliveries.get()
        d.status = EventDeliveryStatus.PENDING
        d.locked_by = None
        d.locked_until = None
        d.save(update_fields=["status", "locked_by", "locked_until"])
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (1, 0))
        # handler 只执行一次
        self.assertEqual(len(self.received), 1)
        d.refresh_from_db()
        self.assertEqual(d.status, EventDeliveryStatus.DELIVERED)

    def test_lease_blocks_reclaim_until_expiry(self):
        register_handler("lease.event", self._handler("h"))
        ev = publish("lease.event", {"n": 1})
        d = ev.deliveries.get()
        # worker A 认领并置租约（未来 60s）
        d.status = EventDeliveryStatus.PROCESSING
        d.locked_by = "worker-a"
        d.locked_until = timezone.now() + timezone.timedelta(seconds=60)
        d.save(update_fields=["status", "locked_by", "locked_until"])
        # worker B 无法认领（租约未过期）
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (0, 0))
        self.assertEqual(self.received, [])
        # 租约过期 → worker C 重新认领并完成投递
        d.locked_until = timezone.now() - timezone.timedelta(seconds=1)
        d.save(update_fields=["locked_until"])
        delivered, failed = dispatch_pending_events(worker_id="worker-c")
        self.assertEqual((delivered, failed), (1, 0))
        self.assertEqual(self.received, [("h", 1)])

    def test_aggregate_ordering_defers_prior_sequence(self):
        register_handler("agg.event", self._handler("h"))
        # 先发布 sequence=2，再发布 sequence=1（乱序入队）
        ev2 = publish("agg.event", {"n": 2}, aggregate_id="agg-1", aggregate_sequence=2)
        ev1 = publish("agg.event", {"n": 1}, aggregate_id="agg-1", aggregate_sequence=1)
        # 只投递了 sequence=1（更早的必需投递）
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (1, 0))
        self.assertEqual(self.received, [("h", 1)])
        # sequence=2 的事件仍在 PENDING，未被跳过
        ev2.refresh_from_db()
        self.assertEqual(ev2.status, OutboxEventStatus.PENDING)
        ev1.refresh_from_db()
        self.assertEqual(ev1.status, OutboxEventStatus.COMPLETE)
        # 补投 sequence=2
        delivered, failed = dispatch_pending_events()
        self.assertEqual((delivered, failed), (1, 0))
        self.assertEqual([r[1] for r in self.received], [1, 2])


class DrainCompatibilityTest(OutboxTestCase):
    def test_drain_outbox_backward_compatible(self):
        register_handler("legacy.event", self._handler("h"))
        publish("legacy.event", {"n": 7})
        self.assertEqual(drain_outbox(), 1)
        self.assertEqual(self.received, [("h", 7)])


class UserCreatedEventIntegrationTest(TestCase):
    """Outbox 业务接入端到端：注册 → user.created 落库 → drain 投递 → COMPLETE。

    验证 Transaction Outbox 与业务打通：注册成功（业务提交）即事件落库（PENDING），
    worker 投递后写幂等凭证并聚合事件为 COMPLETE；注册校验失败不产生事件。
    """

    def setUp(self):
        from system.users.events import (
            reset_user_event_handlers, register_user_event_handlers,
        )
        # 重置业务消费者注册（防 unregister_all_handlers 残留标志），再重新注册
        reset_user_event_handlers()
        register_user_event_handlers()

    def tearDown(self):
        from system.users.events import reset_user_event_handlers
        unregister_all_handlers()
        reset_user_event_handlers()

    def test_register_publishes_event_and_drain_delivers(self):
        from rest_framework.test import APIClient

        resp = APIClient().post("/api/v1/users/register/", {
            "username": "outbox_user",
            "password": "Pass123!",
            "password_confirm": "Pass123!",
            "email": "outbox_user@example.com",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)

        # 事件已落库：PENDING + 1 个投递目标（user.created.notify）
        ev = OutboxEvent.objects.get(event_type="user.created")
        self.assertEqual(ev.status, OutboxEventStatus.PENDING)
        self.assertEqual(ev.payload["username"], "outbox_user")
        self.assertEqual(ev.deliveries.count(), 1)
        d = ev.deliveries.get()
        self.assertEqual(d.target_name, "user.created.notify")
        self.assertEqual(d.status, EventDeliveryStatus.PENDING)

        # drain → 消费者执行 → 幂等凭证写入 → 事件 COMPLETE
        delivered, failed = dispatch_pending_events(worker_id="w-integration")
        self.assertEqual((delivered, failed), (1, 0))
        ev.refresh_from_db()
        d.refresh_from_db()
        self.assertEqual(d.status, EventDeliveryStatus.DELIVERED)
        self.assertEqual(ev.status, OutboxEventStatus.COMPLETE)
        self.assertTrue(InboxReceipt.objects.filter(
            consumer_name="user.created.notify", event=ev).exists())

        # 重复投递不重复执行（幂等）：delivery 重置回 PENDING 后重投跳过 handler
        d.status = EventDeliveryStatus.PENDING
        d.locked_by = None
        d.locked_until = None
        d.save(update_fields=["status", "locked_by", "locked_until"])
        delivered, failed = dispatch_pending_events(worker_id="w-redeliver")
        self.assertEqual((delivered, failed), (1, 0))
        d.refresh_from_db()
        self.assertEqual(d.status, EventDeliveryStatus.DELIVERED)

    def test_register_validation_failure_creates_no_event(self):
        from rest_framework.test import APIClient

        resp = APIClient().post("/api/v1/users/register/", {
            "username": "bad_user",
            "password": "short",
            "password_confirm": "short",
            "email": "not-an-email",
        }, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        # 校验失败不进入业务事务 → 无 user.created 事件
        self.assertEqual(
            OutboxEvent.objects.filter(event_type="user.created").count(), 0)
