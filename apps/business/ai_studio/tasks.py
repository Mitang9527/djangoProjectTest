"""AI 创作工作室 - Celery 异步任务

仅在 settings.AI_STUDIO_SYNC=False 时由 create_generation_task 调度。
具体生成逻辑由 services.run_generation 按渠道 provider 分发
（成功 confirm / 失败由本模块兜底 refund）。

重试与熔断统一使用 framework.reliability（替代手写 max_retries/self.retry）。
"""
from celery import shared_task
from framework.reliability import retry, circuit_breaker, CircuitOpenError
from loguru import logger

from .services import run_generation


@circuit_breaker(
    name="ai_generation",
    failure_threshold=5,
    recovery_time=60,
    expected_exceptions=(Exception,),
)
@retry(
    max_attempts=3,
    backoff="exponential",
    jitter=True,
    retry_on=(Exception,),
    give_up_on=(CircuitOpenError,),
)
def _run_generation(task_id: str) -> None:
    """带重试 + 熔断的生成执行（失败由外层任务负责返还额度）。"""
    run_generation(task_id)


@shared_task(name="ai_studio.generate_task")
def generate_task(task_id: str):
    """异步生成：失败则返还额度。

    重试/熔断在 _run_generation 内完成；全部耗尽后仍失败才进入本函数
    的兜底逻辑返还额度。
    """
    try:
        _run_generation(task_id)
    except Exception as exc:
        from .models import GenerationTask, UserQuota
        from .services import refund

        try:
            task = GenerationTask.objects.get(id=task_id)
            task.status = 'FAILED'
            task.error_msg = str(exc)
            task.save(update_fields=['status', 'error_msg'])
            quota = UserQuota.objects.get(user=task.user)
            refund(quota, task)
        except Exception:
            pass
        logger.exception("生成任务 %s 最终失败，已返还额度", task_id)
        raise
