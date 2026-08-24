"""
framework.tasks — 可靠的 Celery 任务包装器。

把 framework.reliability 的 ``retry``（指数退避 + 抖动）与 ``circuit_breaker``
（熔断）原语一键注入到 Celery task，避免每个任务手搓容错逻辑。

用法::

    from framework.tasks import reliable_task
    from myproj.celery import app

    @reliable_task(app, retry=dict(max_attempts=5), circuit=dict(name="send_email"))
    def send_email(tenant_id: str, payload: dict):
        ...

等价于先 ``@circuit_breaker`` 再 ``@retry`` 最后 ``@app.task`` 的组合，
并保留 task 实例在 ``func.circuit_breaker`` 上供监控。
"""
from framework.tasks.core import reliable_task
from framework.reliability.circuit_breaker import CircuitOpenError

__all__ = ["reliable_task", "CircuitOpenError"]
