"""AI 创作工作室 - Celery 异步任务

仅在 settings.AI_STUDIO_SYNC=False 时由 create_generation_task 调度。
mock 阶段直接复用 services.run_mock_generation；接入真实模型时在
run_mock_generation 内替换推理调用即可（成功 confirm / 失败 refund）。
"""
from celery import shared_task

from .services import run_mock_generation


@shared_task(bind=True, max_retries=2)
def generate_task(self, task_id: str):
    try:
        run_mock_generation(task_id)
    except Exception as exc:  # 失败则返还额度
        from .models import GenerationTask, UserQuota
        from .services import refund

        try:
            task = GenerationTask.objects.get(id=task_id)
            task.status = "FAILED"
            task.error_msg = str(exc)
            task.save()
            quota = UserQuota.objects.get(user_id=task.user_id)
            refund(quota, task)
        except Exception:
            pass
        raise
