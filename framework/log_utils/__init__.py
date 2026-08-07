"""
日志工具集 — loguru 接管 + 多 Logger 分离。

用法:
    from loguru import logger                          # 通用日志 → app.log
    from framework.log_utils import celery_logger           # Celery 任务 → celery.log
    from framework.log_utils import api_logger              # API 请求 → api.log
    from framework.log_utils import LogManager              # 初始化入口 (settings 调用)
    from framework.log_utils import RateLimitFilter         # 日志采样器
    from framework.log_utils import mark_sentry_enabled     # Sentry 就绪通知

所有 ERROR+ 日志自动汇集到 error.log (跨域聚合)。
生产模式额外输出 JSON 结构化日志 (适配 ELK/Loki/Grafana)。
"""

from framework.log_utils.loguru_control import (
    LogManager,
    InterceptHandler,
    RateLimitFilter,
    celery_logger,
    api_logger,
    mark_sentry_enabled,
)

__all__ = [
    "LogManager",
    "InterceptHandler",
    "RateLimitFilter",
    "celery_logger",
    "api_logger",
    "mark_sentry_enabled",
]
