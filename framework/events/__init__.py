"""
framework.events — 领域事件总线 + Transaction Outbox。

解耦业务与通知 / 审计 / 索引等下游：业务 publish 事件，worker 异步投递。
"""
from framework.events.publisher import publish, register_handler
from framework.events.worker import drain_outbox

__all__ = ["publish", "register_handler", "drain_outbox"]
