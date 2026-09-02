"""
Outbox 投递 worker（at-least-once + 幂等）。

dispatch_pending_events():
    - 认领「可投递」的 EventDelivery（状态 PENDING/PROCESSING、available_at 到期、
      租约未锁或已过期），PG 下 select_for_update(skip_locked=True) 并发抢单，
      SQLite（开发/测试）降级为普通查询（单写者天然串行）；
    - 认领后写租约（locked_by / locked_until），调用对应 handler 投递；
    - 本地消费成功写 InboxReceipt（幂等凭证），重投时跳过重复执行；
    - 失败按指数退避（min(300, 2**attempts) 秒）重试，超限进入 DEAD_LETTER。

requeue_dead_letter(event_id): 人工恢复死信事件及其投递目标（重置计数与锁）。

可由管理命令 `python manage.py outbox_drain` 触发，或注册进 Celery beat 周期调用。
"""
from typing import Optional, Tuple

from datetime import timedelta
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from loguru import logger

from framework.events.publisher import _HANDLERS

# 单个 worker 认领上限
DEFAULT_MAX_EVENTS = 100
# 投递最大重试次数（超过进入死信）
DEFAULT_MAX_ATTEMPTS = 8
# 租约时长（秒）：worker 认领后在锁期内投递；崩溃后锁自然过期可被重新认领
DEFAULT_LEASE_SECONDS = 60
# 指数退避上限（秒）
_MAX_BACKOFF = 300


def _uses_pg() -> bool:
    return connection.vendor == "postgresql"


def _claimable_deliveries(now, limit: int, max_attempts: int):
    """返回可认领的投递目标 queryset（PG 行锁 + skip_locked，SQLite 降级）。"""
    from framework.events.models import EventDelivery, EventDeliveryStatus

    qs = (
        EventDelivery.objects.select_related("event")
        .filter(
            status__in=[EventDeliveryStatus.PENDING, EventDeliveryStatus.PROCESSING],
            available_at__lte=now,
        )
        .filter(Q(locked_until__isnull=True) | Q(locked_until__lte=now))
        .order_by("available_at", "id")[:limit]
    )
    if _uses_pg():
        qs = qs.select_for_update(skip_locked=True)
    return list(qs)


def dispatch_pending_events(
    *,
    max_events: int = DEFAULT_MAX_EVENTS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    worker_id: Optional[str] = None,
) -> Tuple[int, int]:
    """投递一批可认领事件。返回 (成功数, 失败数)。"""
    import uuid

    from framework.events.models import (
        EventDelivery, EventDeliveryStatus, InboxReceipt, OutboxEventStatus,
    )

    worker_id = worker_id or f"worker-{uuid.uuid4()}"
    now = timezone.now()
    deliveries = _claimable_deliveries(now, max_events, max_attempts)
    delivered = 0
    failed = 0

    for delivery in deliveries:
        event = delivery.event
        # 防御：父事件被删（CASCADE 下理论不发生）
        if event is None:
            continue

        # 聚合顺序约束：同一聚合存在更早的必需投递未完成 → 本轮跳过
        if not _delivery_can_run(delivery, event):
            continue

        # 认领：写租约（乐观，SQLite 单写者；PG 已在行锁内）
        delivery.status = EventDeliveryStatus.PROCESSING
        delivery.locked_by = worker_id
        delivery.locked_until = now + timedelta(seconds=lease_seconds)
        delivery.save(update_fields=["status", "locked_by", "locked_until"])

        registration = _registration_for_delivery(event.event_type, delivery.target_name)
        if registration is None:
            _record_delivery_failure(
                delivery, event, error="DELIVERY_TARGET_UNAVAILABLE",
                max_attempts=max_attempts,
            )
            failed += 1
            continue

        # 幂等检查：本地消费者已成功消费过 → 直接置 DELIVERED（不重复执行）
        receipt_exists = False
        if delivery.target_type == "LOCAL_CONSUMER":
            receipt_exists = InboxReceipt.objects.filter(
                consumer_name=delivery.target_name, event=event).exists()
        if receipt_exists:
            _mark_delivered(delivery)
            _refresh_event_status(event)
            delivered += 1
            continue

        try:
            with transaction.atomic():
                registration.handler(event, event.payload)
                if delivery.target_type == "LOCAL_CONSUMER":
                    # 与 handler 同事务写幂等凭证：handler 成功 = 凭证落库
                    InboxReceipt.objects.create(
                        consumer_name=delivery.target_name, event=event)
                _mark_delivered(delivery)
            _refresh_event_status(event)
            delivered += 1
        except Exception as exc:  # handler 异常不得终止 worker 循环
            logger.exception("Outbox delivery %s failed", delivery.pk)
            _record_delivery_failure(
                delivery, event, error=_delivery_error(exc), max_attempts=max_attempts)
            failed += 1

    if delivered or failed:
        logger.info(
            "[Outbox] worker=%s 完成一轮投递: delivered=%d failed=%d",
            worker_id, delivered, failed,
        )
    return delivered, failed


def requeue_dead_letter(*, event_id) -> None:
    """人工恢复死信事件及其投递目标（重置计数、锁与错误）。"""
    from framework.events.models import (
        EventDelivery, EventDeliveryStatus, OutboxEvent, OutboxEventStatus,
    )

    event = OutboxEvent.objects.filter(pk=event_id).first()
    if event is None:
        raise ValueError(f"事件不存在: {event_id}")

    now = timezone.now()
    event.status = OutboxEventStatus.PENDING
    event.attempts = 0
    event.last_error = None
    event.dead_lettered_at = None
    event.completed_at = None
    event.save(update_fields=[
        "status", "attempts", "last_error", "dead_lettered_at", "completed_at"])

    for delivery in EventDelivery.objects.filter(event=event):
        if delivery.status != EventDeliveryStatus.DEAD_LETTER:
            continue
        delivery.status = EventDeliveryStatus.PENDING
        delivery.attempts = 0
        delivery.available_at = now
        delivery.locked_by = None
        delivery.locked_until = None
        delivery.dead_lettered_at = None
        delivery.last_error = None
        delivery.save(update_fields=[
            "status", "attempts", "available_at", "locked_by",
            "locked_until", "dead_lettered_at", "last_error"])


def count_pending_events(*, event_type: Optional[str] = None) -> int:
    """当前待投递事件数（监控 / 告警用）。"""
    from framework.events.models import OutboxEvent, OutboxEventStatus

    qs = OutboxEvent.objects.filter(status=OutboxEventStatus.PENDING)
    if event_type:
        qs = qs.filter(event_type=event_type)
    return qs.count()


def drain_outbox(limit: int = DEFAULT_MAX_EVENTS) -> int:
    """兼容旧 API：单次投递一批，返回成功数。"""
    delivered, _ = dispatch_pending_events(max_events=limit)
    return delivered


# ── 内部工具 ──────────────────────────────────────────

def _registration_for_delivery(event_type: str, target_name: str):
    for registration in _HANDLERS.get(event_type, []):
        if registration.consumer_name == target_name:
            return registration
    return None


def _delivery_can_run(delivery, event) -> bool:
    """同一聚合的严格顺序约束：有更早的必需投递未完成则不投（可选项）。"""
    if event.aggregate_sequence is None:
        return True
    from framework.events.models import EventDelivery, EventDeliveryStatus

    prior = (
        EventDelivery.objects.filter(
            event__aggregate_id=event.aggregate_id,
            event__aggregate_sequence__lt=event.aggregate_sequence,
            target_name=delivery.target_name,
            is_required=True,
        )
        .exclude(status=EventDeliveryStatus.DELIVERED)
        .exists()
    )
    return not prior


def _record_delivery_failure(delivery, event, *, error: str, max_attempts: int) -> None:
    """记录投递失败：指数退避重试，超限转死信。"""
    from framework.events.models import EventDeliveryStatus

    now = timezone.now()
    delivery.attempts += 1
    delivery.last_error = error[:2000]
    delivery.locked_by = None
    delivery.locked_until = None
    if delivery.attempts >= max_attempts:
        delivery.status = EventDeliveryStatus.DEAD_LETTER
        delivery.dead_lettered_at = now
    else:
        delivery.status = EventDeliveryStatus.PENDING
        delivery.available_at = now + timedelta(
            seconds=min(_MAX_BACKOFF, 2 ** delivery.attempts))
    delivery.save(update_fields=[
        "attempts", "last_error", "locked_by", "locked_until",
        "status", "dead_lettered_at", "available_at"])
    _refresh_event_status(event)


def _mark_delivered(delivery) -> None:
    from framework.events.models import EventDeliveryStatus

    delivery.status = EventDeliveryStatus.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.locked_by = None
    delivery.locked_until = None
    delivery.last_error = None
    delivery.save(update_fields=[
        "status", "delivered_at", "locked_by", "locked_until", "last_error"])


def _refresh_event_status(event) -> None:
    """由投递聚合推进事件状态：必需目标全成 → COMPLETE；任一死信 → DEAD_LETTER。"""
    from framework.events.models import EventDelivery, EventDeliveryStatus, OutboxEventStatus

    deliveries = list(event.deliveries.all())
    required = [d for d in deliveries if d.is_required]
    now = timezone.now()
    event.attempts = max((d.attempts for d in deliveries), default=0)
    required_dead = any(d.status == EventDeliveryStatus.DEAD_LETTER for d in required)
    required_complete = (
        bool(required) and
        all(d.status == EventDeliveryStatus.DELIVERED for d in required)
    )

    if required_dead:
        event.status = OutboxEventStatus.DEAD_LETTER
        event.dead_lettered_at = now
        event.completed_at = None
        event.last_error = next(
            (d.last_error for d in required
             if d.status == EventDeliveryStatus.DEAD_LETTER), None)
    elif required_complete:
        event.status = OutboxEventStatus.COMPLETE
        event.completed_at = now
        event.dead_lettered_at = None
        event.last_error = None
    else:
        event.status = OutboxEventStatus.PENDING
        event.completed_at = None
    event.save(update_fields=[
        "status", "attempts", "last_error", "dead_lettered_at", "completed_at"])


def _delivery_error(exc: Exception) -> str:
    """持久化稳定、不泄敏的失败分类。"""
    return f"DELIVERY_HANDLER_FAILED:{type(exc).__name__}"
