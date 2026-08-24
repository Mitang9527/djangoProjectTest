"""
追踪中间件：为每个入站请求建立/传播 trace。

- 优先复用上游传入的 ``X-Trace-Id`` 或 W3C ``traceparent``（网关 / 上游服务已生成）。
- 否则新生成 trace_id。
- 响应头回写 ``X-Trace-Id``，方便前端串联排障。
- 同时 set 到 contextvars，供日志拦截器 / 业务代码读取。

接入（可选）：
    MIDDLEWARE += ['framework.tracing.middleware.TracingMiddleware']
"""
from framework.tracing.context import (
    get_trace_id,
    new_trace_id,
    reset_trace_context,
    set_trace_context,
)


class TracingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_TRACE_ID") or request.META.get("HTTP_TRACEPARENT")
        trace_id = None
        if incoming:
            # W3C traceparent: 00-<trace_id>-<span_id>-<flags>
            trace_id = incoming.split("-")[1] if incoming.startswith("00-") else incoming
        token = set_trace_context(trace_id=trace_id)
        try:
            response = self.get_response(request)
            response["X-Trace-Id"] = get_trace_id()
            return response
        finally:
            reset_trace_context(token)
