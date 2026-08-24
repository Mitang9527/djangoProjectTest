"""
事件发布。

publish(event_type, payload, use_outbox=True):
    - use_outbox=True 且 OutboxEvent 可用（已迁移）时写入 DB（PENDING），保证不丢；
    - 否则降级为调用注册的内存 handler（适合无 DB 依赖的轻量场景 / 测试）。
"""
from typing import Any, Callable, Dict, Optional

_HANDLERS: Dict[str, Callable] = {}


def register_handler(event_type: str, fn: Callable[[Dict[str, Any]], None]) -> None:
    _HANDLERS[event_type] = fn


def publish(
    event_type: str,
    payload: Dict[str, Any],
    *,
    use_outbox: bool = True,
) -> Optional[object]:
    if use_outbox:
        try:
            from framework.events.models import OutboxEvent

            return OutboxEvent.objects.create(event_type=event_type, payload=payload)
        except Exception:
            # model 未迁移 / framework 未加入 INSTALLED_APPS → 降级内存直发
            pass
    handler = _HANDLERS.get(event_type)
    if handler:
        return handler(payload)
    return None
