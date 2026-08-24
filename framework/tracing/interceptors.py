"""
出站 HTTP 追踪拦截器：把当前 trace 注入下游请求头。

- 注入 W3C ``traceparent``（与 OpenTelemetry 生态兼容）。
- 同时写入 ``X-Trace-Id``，与 LoggingInterceptor 的字段对齐，方便跨服务日志关联。
"""
from typing import Any, Dict, Optional

from framework.tracing.context import get_trace_id, new_trace_id, traceparent


class TracingInterceptor:
    """出站请求链路透传。"""

    def before_request(
        self, method: str, url: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        headers = dict(kwargs.get("headers") or {})
        headers["traceparent"] = traceparent()
        headers.setdefault("X-Trace-Id", get_trace_id() or new_trace_id()[:16])
        kwargs["headers"] = headers
        return kwargs

    def after_response(
        self, method: str, url: str, response: Any, elapsed_ms: float
    ) -> None:
        return None

    def on_error(
        self, method: str, url: str, exception: BaseException, elapsed_ms: float
    ) -> None:
        return None
