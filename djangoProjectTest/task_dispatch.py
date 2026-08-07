"""跨服务任务投递统一入口。

把主平台对独立服务（AI 服务 / 通知服务）的 RabbitMQ 投递逻辑收敛到一处，
避免各调用方重复编写 ``send_task`` + 异常处理 / 降级 样板。

用法::

    from djangoProjectTest.task_dispatch import send_cross_service_task

    # 仅投递，失败抛异常由调用方处理（如返回 503）
    send_cross_service_task(
        "ai_studio_app.tasks.handle_generation",
        queue="ai_studio.generate",
        payload=payload,
        throw=True,
    )

    # 投递 + 本地降级（broker 不可用时走 fallback）
    result = send_cross_service_task(
        "notice_app.tasks.send_notification",
        queue="notice.send",
        payload=payload,
        fallback=local_dispatcher,
    )
"""
from __future__ import annotations

import logging

from djangoProjectTest.celery import app as celery_app

logger = logging.getLogger(__name__)


def send_cross_service_task(
    task_name: str,
    queue: str,
    payload: dict,
    *,
    fallback=None,
    throw: bool = False,
):
    """经共享 RabbitMQ 把任务投递到指定队列。

    Args:
        task_name: 完整任务路径，如 ``"ai_studio_app.tasks.handle_generation"``。
        queue: 目标队列，如 ``"ai_studio.generate"``。
        payload: 任务参数（作为任务的唯一位置参数传递）。
        fallback: 可选可调用；broker 不可用时调用之以本地降级（无参调用）。
        throw: 无 fallback 且投递失败时是否重新抛出异常；
            ``True`` 抛出，``False``（默认）返回结构化失败结果。

    Returns:
        dict: ``{"ok", "via", "success", "error", ["result"]}``，
        ``via`` ∈ ``{"service", "local", "none"}``。
    """
    try:
        celery_app.send_task(task_name, args=[payload], queue=queue)
        return {"ok": True, "via": "service", "success": True, "error": None}
    except Exception as exc:  # 队列不可用（如未配置 CELERY_BROKER_URL）
        logger.warning("跨服务任务投递失败 (%s -> %s): %s", task_name, queue, exc)
        if fallback is not None:
            try:
                local_result = fallback()
                return {
                    "ok": True,
                    "via": "local",
                    "success": True,
                    "error": None,
                    "result": local_result,
                }
            except Exception as fexc:
                logger.exception("本地降级发送也失败")
                return {"ok": False, "via": "none", "success": False, "error": str(fexc)}
        if throw:
            raise
        return {"ok": False, "via": "none", "success": False, "error": str(exc)}
