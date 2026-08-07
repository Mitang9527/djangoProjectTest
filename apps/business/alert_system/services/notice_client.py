"""
通知服务客户端 — 把通知投递到独立 notice_service（RabbitMQ 队列 notice.send）。

设计:
- 主平台不再直接发送通知，而是经共享 RabbitMQ 把任务投递给通知服务 worker。
- broker 不可用时降级为本地 NotificationDispatcher，保证告警不丢。
- 返回 dict: {ok, via("service"|"local"|"none"), success, error}（见 task_dispatch）
"""
from __future__ import annotations

from djangoProjectTest.task_dispatch import send_cross_service_task

NOTICE_QUEUE = "notice.send"
NOTICE_TASK = "notice_app.tasks.send_notification"


def send_notification(payload: dict, fallback=None) -> dict:
    """投递通知到通知服务；失败则执行 fallback（本地降级）。"""
    return send_cross_service_task(
        NOTICE_TASK, queue=NOTICE_QUEUE, payload=payload, fallback=fallback
    )
