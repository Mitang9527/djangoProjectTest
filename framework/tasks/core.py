"""
可靠任务核心。

reliable_task(app, *, retry=None, circuit=None, bind=False, name=None, queue=None, **task_kwargs)
    app       : Celery 应用实例（各服务 celery.py 中的 app）。
    retry     : 传给 framework.reliability.retry 的关键字（None 时不套重试）。
    circuit   : 传给 framework.reliability.circuit_breaker 的关键字；
                其中 'name' 为熔断器名（缺省用函数名），其余透传。
    bind/name/queue/task_kwargs : 透传给 Celery 的 @app.task。

注意：不在此模块顶层 import celery，app 由调用方传入，保证可独立导入与测试。
"""
from typing import Callable, Dict, Optional

from framework.reliability.circuit_breaker import circuit_breaker
from framework.reliability.retry import retry


def reliable_task(
    app,
    *,
    retry: Optional[Dict] = None,
    circuit: Optional[Dict] = None,
    bind: bool = False,
    name: Optional[str] = None,
    queue: Optional[str] = None,
    **task_kwargs,
) -> Callable:
    """装饰器工厂：组合 熔断 + 重试 + Celery 注册。"""

    def decorator(func: Callable) -> Callable:
        wrapped = func
        if circuit is not None:
            cb_conf = dict(circuit)
            cb_name = cb_conf.pop("name", func.__name__)
            wrapped = circuit_breaker(cb_name, **cb_conf)(wrapped)
        if retry is not None:
            wrapped = retry(**retry)(wrapped)
        register_kwargs: Dict = dict(task_kwargs)
        if bind:
            register_kwargs["bind"] = True
        if name:
            register_kwargs["name"] = name
        if queue:
            register_kwargs["queue"] = queue
        return app.task(**register_kwargs)(wrapped)

    return decorator
