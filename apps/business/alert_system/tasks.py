"""
告警系统 — Celery 异步任务

任务:
- dispatch_alert:     异步发送告警通知（由 AlertEngine._dispatch_async 调用）
- check_escalations:  定时检查告警升级（建议每 5 分钟由 Celery Beat 调度）

Celery 不可用时自动降级为同步执行。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
    _CELERY_AVAILABLE = True
except ImportError:
    _CELERY_AVAILABLE = False

    def shared_task(*args, **kwargs):  # type: ignore
        """Celery 不可用时的降级装饰器 — 直接同步执行"""
        def decorator(func):
            def wrapper(*inner_args, **inner_kwargs):
                # 模拟 .delay() 接口
                class _SyncResult:
                    def __init__(self, result):
                        self.result = result

                    def get(self):
                        return self.result

                result = func(*inner_args, **inner_kwargs)
                return _SyncResult(result)

            # 模拟 .delay() 方法
            wrapper.delay = lambda *a, **kw: wrapper(*a, **kw)
            return wrapper
        return decorator


@shared_task(name="alert_system.dispatch_alert", bind=True, max_retries=3)
def dispatch_alert(self, history_id: int):
    """
    异步发送告警通知。

    Args:
        history_id: AlertHistory.pk
    """
    try:
        from .models import AlertHistory
        from .services.alert_engine import AlertEngine

        history = AlertHistory.objects.get(pk=history_id)
        AlertEngine._dispatch_sync(history)
        logger.info("告警 %s 通知发送完成", history_id)

    except AlertHistory.DoesNotExist:
        logger.warning("告警 %s 不存在，跳过发送", history_id)

    except Exception as exc:
        logger.error("告警 %s 发送失败: %s", history_id, exc)
        # 重试（指数退避）
        if _CELERY_AVAILABLE:
            raise self.retry(exc=exc, countdown=60 * (2 ** (self.request.retries or 0)))
        else:
            raise


@shared_task(name="alert_system.check_escalations")
def check_escalations():
    """
    定时检查告警升级。
    建议由 Celery Beat 每 5 分钟调度一次。

    配置示例 (django_celery_beat):
        - Name: alert-escalation-check
        - Task: alert_system.check_escalations
        - Interval: every 5 minutes
    """
    try:
        from .services.alert_engine import AlertEngine

        count = AlertEngine.check_escalations()
        if count > 0:
            logger.info("告警升级检查完成: %d 条告警已升级", count)
        return count

    except Exception as exc:
        logger.error("告警升级检查失败: %s", exc)
        raise
