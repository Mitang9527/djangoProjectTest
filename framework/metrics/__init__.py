"""自定义 Prometheus 指标包。

导出所有业务指标与辅助函数，方便其它模块：
    from framework.metrics import API_REQUESTS_TOTAL, CACHE_HITS_TOTAL, ...
    from framework.metrics import (
        record_cache_hit, record_error_log, set_celery_queue_backlog, ...
"""
from .metrics import (
    # ---- 原始指标对象 (Counter / Gauge / Histogram) ----
    ALERTS_TRIGGERED_TOTAL,
    API_ERRORS_TOTAL,
    API_REQUEST_DURATION_SECONDS,
    API_REQUESTS_TOTAL,
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
    CELERY_QUEUE_BACKLOG,
    DB_LONG_TRANSACTIONS,
    DB_QUERY_DURATION_SECONDS,
    DB_SLOW_QUERIES_TOTAL,
    ERROR_LOGS_TOTAL,
    ERROR_LOGS_WINDOW,
    RATE_LIMIT_REJECTIONS_TOTAL,
    WEBSOCKET_ONLINE_USERS,
    # ---- 辅助函数 (record_* / set_* / observe_*) ----
    observe_db_query_duration,
    record_alert_triggered,
    record_cache_hit,
    record_cache_miss,
    record_error_log,
    record_rate_limit_rejection,
    record_slow_query,
    set_celery_queue_backlog,
    set_error_logs_window,
    set_long_transactions,
    set_websocket_online_users,
)

__all__ = [
    # 原始指标对象
    "API_REQUESTS_TOTAL",
    "API_REQUEST_DURATION_SECONDS",
    "API_ERRORS_TOTAL",
    "CACHE_HITS_TOTAL",
    "CACHE_MISSES_TOTAL",
    "RATE_LIMIT_REJECTIONS_TOTAL",
    "WEBSOCKET_ONLINE_USERS",
    "CELERY_QUEUE_BACKLOG",
    "ALERTS_TRIGGERED_TOTAL",
    "ERROR_LOGS_TOTAL",
    "ERROR_LOGS_WINDOW",
    "DB_SLOW_QUERIES_TOTAL",
    "DB_QUERY_DURATION_SECONDS",
    "DB_LONG_TRANSACTIONS",
    # 辅助函数
    "record_cache_hit",
    "record_cache_miss",
    "record_rate_limit_rejection",
    "set_websocket_online_users",
    "set_celery_queue_backlog",
    "record_alert_triggered",
    "record_error_log",
    "set_error_logs_window",
    "record_slow_query",
    "observe_db_query_duration",
    "set_long_transactions",
]
