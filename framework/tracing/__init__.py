"""
framework.tracing — 轻量级分布式追踪（零硬依赖，可降级）。

设计
----
- 核心用 ``contextvars`` 维护 ``trace_id / span_id``，与 log_utils/request_id 的
  ``X-Trace-Id`` 概念对齐，打通「指标(metrics) - 链路(trace) - 日志(log)」三件套。
- 若运行环境安装了 ``opentelemetry``，可在 middleware 中升级为真实 span（见文档）；
  未安装时完全降级为 trace_id 传播，不影响任何现有行为。

组件
----
- TracingMiddleware : 入站请求起一个 trace（取上游 X-Trace-Id / traceparent，否则新生成），
                     响应头回写 X-Trace-Id。
- TracingInterceptor: 出站 HTTP 请求注入 W3C ``traceparent``，打通上下游链路。
- get_trace_id()    : 任意位置读取当前 trace_id（日志/异常埋点用）。
"""
from framework.tracing.context import (
    get_trace_id,
    new_span_id,
    new_trace_id,
    reset_trace_context,
    set_trace_context,
    traceparent,
)
from framework.tracing.middleware import TracingMiddleware
from framework.tracing.interceptors import TracingInterceptor

__all__ = [
    "TracingMiddleware",
    "TracingInterceptor",
    "get_trace_id",
    "set_trace_context",
    "reset_trace_context",
    "traceparent",
    "new_trace_id",
    "new_span_id",
]
