"""
framework 应用模型桥接。

Django 仅扫描各 app 的 ``models`` 模块；框架的 ORM 模型（事务 Outbox 三表）定义在
``framework.events.models``，此处 re-export 以便 Django 模型注册表发现，
app_label 统一为 ``framework``。
"""
from framework.events.models import (  # noqa: F401
    OutboxEvent,
    OutboxEventStatus,
    EventDelivery,
    EventDeliveryStatus,
    EventDeliveryTargetType,
    InboxReceipt,
)

__all__ = [
    "OutboxEvent",
    "OutboxEventStatus",
    "EventDelivery",
    "EventDeliveryStatus",
    "EventDeliveryTargetType",
    "InboxReceipt",
]
