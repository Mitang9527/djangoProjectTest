"""
API 指标采集中间件。

作用：统计每个 API 请求的 数量 / 延迟 / 错误率，并暴露给 Prometheus。
放置位置：MIDDLEWARE 列表末尾（response 阶段最先执行，可拿到最终 status_code）。

排除路径：/metrics、/api/health、静态/媒体/管理后台等内部路径，避免自监控噪声与高基数。
"""
from __future__ import annotations

import time

from django.conf import settings

from framework.metrics.metrics import (
    API_ERRORS_TOTAL,
    API_REQUEST_DURATION_SECONDS,
    API_REQUESTS_TOTAL,
)

# 默认排除的内部/高频路径前缀
_DEFAULT_EXCLUDE = (
    "/metrics",
    "/api/health",
    "/static",
    "/static_root",
    "/media",
    "/admin",
    "/favicon.ico",
)


def _should_exclude(path: str) -> bool:
    exclude = getattr(settings, "METRICS_EXCLUDE_PATHS", _DEFAULT_EXCLUDE)
    return path.startswith(exclude)


class MetricsMiddleware:
    """采集 API 请求数、延迟与错误率指标。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _should_exclude(request.path):
            return self.get_response(request)

        start = time.perf_counter()
        response = self.get_response(request)

        duration = time.perf_counter() - start
        method = request.method or "GET"
        endpoint = self._endpoint_label(request)
        status = str(response.status_code)

        API_REQUESTS_TOTAL.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        API_REQUEST_DURATION_SECONDS.labels(
            method=method, endpoint=endpoint
        ).observe(duration)

        if response.status_code >= 400:
            API_ERRORS_TOTAL.labels(
                method=method, endpoint=endpoint, status=status
            ).inc()

        return response

    @staticmethod
    def _endpoint_label(request) -> str:
        """用 URL name（低基数）作为标签，缺失时回退到 path。"""
        match = getattr(request, "resolver_match", None)
        if match is not None and getattr(match, "view_name", None):
            return str(match.view_name)
        return request.path
