"""AI 创作工作室 - Celery 异步任务

- generate_task：仅在本服务 HTTP 入口 create_generation_task(AI_STUDIO_SYNC=False)
  时被调度，执行单条任务的 mock 生成。
- handle_generation：跨服务入口。主平台经 RabbitMQ 把任务投递到 ai_studio.generate
  队列，本任务在 worker 内创建任务并执行生成（默认同步 mock）；结果存库，
  前端经 WebSocket 主动查询获取。

mock 阶段直接复用 services.run_mock_generation；接入真实模型时在
run_mock_generation 内替换推理调用即可（成功 confirm / 失败 refund）。
"""
from celery import shared_task

from .services import create_generation_task, run_mock_generation


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


@shared_task
def handle_generation(payload: dict):
    """跨服务生成入口：主平台经 MQ 投递。

    payload 字段：user_id, username, kind, prompt,
    ref_image(可选), resolution(可选), count(可选), style(可选), size(可选)
    返回新建任务的 id（str）。
    """
    params = {
        k: payload[k]
        for k in ("kind", "prompt", "ref_image", "resolution", "count", "style", "size")
        if k in payload
    }
    task = create_generation_task(
        payload["user_id"],
        payload.get("username", ""),
        params,
        task_id=payload.get("task_id"),
    )
    return str(task.id)

