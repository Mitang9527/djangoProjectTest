"""
Webhook 事件派发（内存注册表，进程内）。

生产环境可替换为持久化队列 + worker；此处提供最小可用的注册 / 派发能力，
并可与 framework.reliability.retry 组合做失败重试。
"""
from typing import Callable, Dict, Optional


_REGISTRY: Dict[str, Callable] = {}


def register(event_type: str, handler: Callable[[dict], None]) -> None:
    """注册某事件类型的处理函数。"""
    _REGISTRY[event_type] = handler


def dispatch(event_type: str, payload: dict) -> Optional[object]:
    """派发事件到已注册处理函数；无处理器返回 None。"""
    handler = _REGISTRY.get(event_type)
    if handler is None:
        return None
    return handler(payload)


def handlers() -> Dict[str, Callable]:
    return dict(_REGISTRY)
