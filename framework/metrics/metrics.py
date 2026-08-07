"""
自定义 Prometheus 指标定义。

prometheus_client 由 django_prometheus 间接依赖，通常已安装。
若环境中未安装，则所有指标降级为 no-op，不影响业务运行。

指标清单（均带 django_ 前缀，与 django_prometheus 通用指标区分）：
  - django_api_requests_total           API 请求数（method/endpoint/status）
  - django_api_request_duration_seconds API 延迟直方图（method/endpoint）
  - django_api_errors_total             API 错误数（method/endpoint/status）
  - django_cache_hits_total             缓存命中（backend）
  - django_cache_misses_total           缓存未命中（backend）
  - django_rate_limit_rejections_total  限流拒绝（scope）
  - django_websocket_online_users       当前 WebSocket 在线用户（Gauge）
  - django_celery_queue_backlog         Celery 队列积压近似（queue）
  - django_alerts_triggered_total       告警触发数（level）
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram

    _HAS_PROM = True
except ImportError:  # pragma: no cover - 防御性降级
    _HAS_PROM = False

    class _NoopMetric:
        """无 prometheus_client 时的空操作指标，接口与真实指标对齐。"""

        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            return None

        def dec(self, *args, **kwargs):
            return None

        def set(self, *args, **kwargs):
            return None

        def observe(self, *args, **kwargs):
            return None

        def time(self, *args, **kwargs):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            return _Ctx()


def _noop() -> _NoopMetric:
    return _NoopMetric()


if _HAS_PROM:
    API_REQUESTS_TOTAL = Counter(
        "django_api_requests_total",
        "Total number of API requests.",
        ["method", "endpoint", "status"],
    )
    API_REQUEST_DURATION_SECONDS = Histogram(
        "django_api_request_duration_seconds",
        "API request duration in seconds.",
        ["method", "endpoint"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    API_ERRORS_TOTAL = Counter(
        "django_api_errors_total",
        "Total number of API errors (status >= 400).",
        ["method", "endpoint", "status"],
    )
    CACHE_HITS_TOTAL = Counter(
        "django_cache_hits_total",
        "Total cache hits.",
        ["backend"],
    )
    CACHE_MISSES_TOTAL = Counter(
        "django_cache_misses_total",
        "Total cache misses.",
        ["backend"],
    )
    RATE_LIMIT_REJECTIONS_TOTAL = Counter(
        "django_rate_limit_rejections_total",
        "Total rate-limit rejections.",
        ["scope"],
    )
    WEBSOCKET_ONLINE_USERS = Gauge(
        "django_websocket_online_users",
        "Current number of online WebSocket users.",
    )
    CELERY_QUEUE_BACKLOG = Gauge(
        "django_celery_queue_backlog",
        "Approximate Celery queue backlog (messages awaiting processing).",
        ["queue"],
    )
    ALERTS_TRIGGERED_TOTAL = Counter(
        "django_alerts_triggered_total",
        "Total alerts triggered via AlertEngine.",
        ["level"],
    )
    ERROR_LOGS_TOTAL = Counter(
        "django_error_logs_total",
        "Total ERROR+ log records captured by the error-spike sink.",
        ["source"],
    )
    ERROR_LOGS_WINDOW = Gauge(
        "django_error_logs_window",
        "ERROR+ log count within the current monitoring window (set by beat task).",
    )
    DB_SLOW_QUERIES_TOTAL = Counter(
        "django_db_slow_queries_total",
        "Total slow DB queries exceeding the threshold.",
        ["alias"],
    )
    DB_QUERY_DURATION_SECONDS = Histogram(
        "django_db_query_duration_seconds",
        "DB query execution duration in seconds.",
        ["alias"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    DB_LONG_TRANSACTIONS = Gauge(
        "django_db_long_transactions",
        "Number of open transactions exceeding the long-transaction threshold.",
        ["alias"],
    )
else:  # pragma: no cover
    API_REQUESTS_TOTAL = _noop()
    API_REQUEST_DURATION_SECONDS = _noop()
    API_ERRORS_TOTAL = _noop()
    CACHE_HITS_TOTAL = _noop()
    CACHE_MISSES_TOTAL = _noop()
    RATE_LIMIT_REJECTIONS_TOTAL = _noop()
    WEBSOCKET_ONLINE_USERS = _noop()
    CELERY_QUEUE_BACKLOG = _noop()
    ALERTS_TRIGGERED_TOTAL = _noop()
    ERROR_LOGS_TOTAL = _noop()
    ERROR_LOGS_WINDOW = _noop()
    DB_SLOW_QUERIES_TOTAL = _noop()
    DB_QUERY_DURATION_SECONDS = _noop()
    DB_LONG_TRANSACTIONS = _noop()


def record_cache_hit(backend: str = "default") -> None:
    """记录一次缓存命中。"""
    CACHE_HITS_TOTAL.labels(backend=backend).inc()


def record_cache_miss(backend: str = "default") -> None:
    """记录一次缓存未命中。"""
    CACHE_MISSES_TOTAL.labels(backend=backend).inc()


def record_rate_limit_rejection(scope: str = "default") -> None:
    """记录一次限流拒绝。"""
    RATE_LIMIT_REJECTIONS_TOTAL.labels(scope=scope).inc()


def set_websocket_online_users(value: int) -> None:
    """设置当前 WebSocket 在线用户数。"""
    WEBSOCKET_ONLINE_USERS.set(value)


def set_celery_queue_backlog(queue: str, value: int) -> None:
    """设置某个 Celery 队列的积压量。"""
    CELERY_QUEUE_BACKLOG.labels(queue=queue).set(value)


def record_alert_triggered(level: str = "warning") -> None:
    """记录一次告警触发。"""
    ALERTS_TRIGGERED_TOTAL.labels(level=level).inc()


def record_error_log(source: str = "app") -> None:
    """记录一条 ERROR+ 日志（供 Prometheus 累计）。"""
    ERROR_LOGS_TOTAL.labels(source=source).inc()


def set_error_logs_window(value: int) -> None:
    """设置当前窗口内 ERROR+ 日志数（由 beat 任务写入）。"""
    ERROR_LOGS_WINDOW.set(value)


def record_slow_query(alias: str = "default") -> None:
    """记录一次慢查询。"""
    DB_SLOW_QUERIES_TOTAL.labels(alias=alias).inc()


def observe_db_query_duration(alias: str, seconds: float) -> None:
    """记录一次 DB 查询耗时（秒）。"""
    DB_QUERY_DURATION_SECONDS.labels(alias=alias).observe(seconds)


def set_long_transactions(alias: str, value: int) -> None:
    """设置某 alias 当前长事务数量。"""
    DB_LONG_TRANSACTIONS.labels(alias=alias).set(value)
