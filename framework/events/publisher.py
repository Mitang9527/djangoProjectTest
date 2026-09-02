"""
事件发布（Transaction Outbox 入口）。

publish(event_type, payload, ...):
    - use_outbox=True 且 OutboxEvent 可用（framework 已迁移）→ 写入 DB：
      创建 OutboxEvent + 为每个注册的投递目标创建 EventDelivery（PENDING）；
      零投递目标时事件直接 COMPLETE（无需消费）。
    - 否则降级为调用注册的内存 handler（适合无 DB 依赖的轻量场景 / 测试）。

注册：
    register_handler(event_type, fn, consumer_name="default", required=True)
        注册本地消费者（LOCAL_CONSUMER）。
    register_external_delivery(event_type, target_name, fn, required=True)
        注册外部中间件发布器（EXTERNAL_BROKER，如 RabbitMQ / Celery 转发）。

注意：publish 应在业务事务内调用（transaction.atomic），事件与业务变更同事务提交。
"""
from typing import Any, Callable, Dict, Optional

from loguru import logger


class HandlerRegistration:
    __slots__ = ("consumer_name", "handler", "consumer_module", "required", "target_type")

    def __init__(self, consumer_name, handler, *, consumer_module="", required=True,
                 target_type="LOCAL_CONSUMER"):
        self.consumer_name = consumer_name
        self.handler = handler
        self.consumer_module = consumer_module
        self.required = required
        self.target_type = target_type


# event_type -> [HandlerRegistration, ...]（一个事件可扇出到多个目标）
_HANDLERS: Dict[str, list[HandlerRegistration]] = {}


def register_handler(
    event_type: str,
    fn: Callable[[Dict[str, Any]], None],
    *,
    consumer_name: Optional[str] = None,
    consumer_module: str = "",
    required: bool = True,
) -> None:
    """注册本地消费者（LOCAL_CONSUMER）。consumer_name 默认 "default"（兼容旧单 handler 用法）。"""
    _register(event_type, HandlerRegistration(
        consumer_name or "default", fn,
        consumer_module=consumer_module, required=required,
        target_type="LOCAL_CONSUMER",
    ))


def register_external_delivery(
    event_type: str,
    target_name: str,
    fn: Callable[[Dict[str, Any]], None],
    *,
    required: bool = True,
) -> None:
    """注册外部中间件投递目标（EXTERNAL_BROKER）。"""
    _register(event_type, HandlerRegistration(
        target_name, fn, required=required, target_type="EXTERNAL_BROKER",
    ))


def _register(event_type: str, registration: HandlerRegistration) -> None:
    registrations = _HANDLERS.setdefault(event_type, [])
    if any(r.consumer_name == registration.consumer_name for r in registrations):
        raise ValueError(f"重复的事件消费者: {registration.consumer_name}")
    registrations.append(registration)


def unregister_all_handlers() -> None:
    """清空全部注册（测试隔离用）。"""
    _HANDLERS.clear()


def get_handlers(event_type: str) -> list[HandlerRegistration]:
    return list(_HANDLERS.get(event_type, []))


def enqueue_event(
    *,
    event_type: str,
    payload: Dict[str, Any],
    tenant_id: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    aggregate_sequence: Optional[int] = None,
    trace_id: Optional[str] = None,
    event_version: int = 1,
) -> Any:
    """在业务事务内创建 OutboxEvent + 投递目标，返回事件对象。

    零投递目标时事件直接置 COMPLETE（无消费者可消费，等价于已完成）。
    """
    from django.utils import timezone
    from framework.events.models import (
        OutboxEvent, OutboxEventStatus, EventDelivery, EventDeliveryTargetType,
    )

    registrations = _HANDLERS.get(event_type, [])
    now = timezone.now()
    event = OutboxEvent.objects.create(
        event_type=event_type,
        event_version=event_version,
        tenant_id=tenant_id,
        aggregate_id=aggregate_id,
        aggregate_sequence=aggregate_sequence,
        payload=payload,
        trace_id=trace_id,
        occurred_at=now,
        available_at=now,
    )
    if not registrations:
        event.status = OutboxEventStatus.COMPLETE
        event.completed_at = now
        event.save(update_fields=["status", "completed_at"])
        return event

    EventDelivery.objects.bulk_create([
        EventDelivery(
            event=event,
            target_name=r.consumer_name,
            target_type=r.target_type,
            consumer_module=r.consumer_module or None,
            is_required=r.required,
            available_at=now,
        )
        for r in registrations
    ])
    return event


def publish(
    event_type: str,
    payload: Dict[str, Any],
    *,
    use_outbox: bool = True,
    tenant_id: Optional[str] = None,
    aggregate_id: Optional[str] = None,
    aggregate_sequence: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> Optional[object]:
    """发布事件：优先写 Outbox，不可用（未迁移 / 未安装）时降级内存直发。"""
    if use_outbox:
        try:
            return enqueue_event(
                event_type=event_type,
                payload=payload,
                tenant_id=tenant_id,
                aggregate_id=aggregate_id,
                aggregate_sequence=aggregate_sequence,
                trace_id=trace_id,
            )
        except Exception:
            # model 未迁移 / framework 未加入 INSTALLED_APPS → 降级内存直发
            logger.warning("[Outbox] Outbox 不可用，降级内存直发 event_type=%s", event_type)

    # 内存直发：只调第一个本地 handler（旧语义：单 handler 直发，event=None）
    registrations = _HANDLERS.get(event_type, [])
    if registrations:
        return registrations[0].handler(None, payload)
    return None
