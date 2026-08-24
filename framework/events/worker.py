"""
Outbox 投递 worker。

drain_outbox(limit) 取出 PENDING 事件，调用注册 handler 投递；成功置 SENT，失败置 FAILED。
可由 Celery beat / 定时任务周期性调用，与现有 RabbitMQ + Celery 体系配合。
"""
from typing import Dict, Any

from framework.events.publisher import _HANDLERS


def drain_outbox(limit: int = 100) -> int:
    try:
        from framework.events.models import OutboxEvent
    except Exception:
        return 0

    pending = OutboxEvent.objects.filter(status=OutboxEvent.Status.PENDING)[:limit]
    done = 0
    for ev in pending:
        handler = _HANDLERS.get(ev.event_type)
        try:
            if handler:
                handler(ev.payload)
            ev.status = OutboxEvent.Status.SENT
            ev.dispatched_at = __import__("django.utils.timezone").utils.timezone.now()
            ev.save(update_fields=["status", "dispatched_at"])
            done += 1
        except Exception:
            ev.status = OutboxEvent.Status.FAILED
            ev.save(update_fields=["status"])
    return done
