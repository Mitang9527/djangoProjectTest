"""通知服务 - Celery 异步任务

- send_notification: 跨服务入口。主平台经 RabbitMQ 把通知投递到 notice.send
  队列，本任务在 worker 内调用 NotificationDispatcher 分发到各渠道，返回结果字典。

幂等：相同内容（channels/title/content/level）的通知在 TTL 内只真正发送一次，
避免下游重复投递或客户端重试导致的重复告警。Redis 不可用时自动降级为无去重。
"""
import hashlib
import json
import logging

from celery import shared_task
from framework.idempotency import idempotent_context
from framework.idempotency.exceptions import IdempotencyInProgress

from .services import NotificationDispatcher

logger = logging.getLogger(__name__)


def _notify_key(payload: dict) -> str:
    """按通知内容生成稳定指纹 key。"""
    fp = json.dumps(
        {
            "channels": payload.get("channels"),
            "title": payload.get("title"),
            "content": payload.get("content"),
            "level": payload.get("level"),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return "notice:" + hashlib.sha256(fp.encode("utf-8")).hexdigest()[:32]


@shared_task(name="notice_app.tasks.send_notification")
def send_notification(payload: dict):
    """跨服务通知入口：主平台经 MQ 投递。

    payload 字段：channels(list[str]), title, content,
    level("info"|"warning"|"error"|"critical"), context(dict)
    返回各渠道结果: {"email": {"success": bool, "error": str|None}, ...}
    """
    key = _notify_key(payload)
    try:
        with idempotent_context(key=key, ttl=3600) as ctx:
            if ctx.is_replay:
                return ctx.replayed_response
            results = NotificationDispatcher.dispatch(
                channels=payload.get("channels", []),
                title=payload.get("title", ""),
                content=payload.get("content", ""),
                level=payload.get("level", "warning"),
                context=payload.get("context", {}) or {},
            )
            ctx.store(results)
            return results
    except IdempotencyInProgress:
        # 相同通知正在由其他 worker 发送，跳过本次重复投递
        logger.info("相同通知正在发送中，跳过重复发送: %s", key[:16])
        return {"_dedup": "in_progress_skip"}
