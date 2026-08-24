"""
追踪上下文（contextvars）。

不依赖任何第三方库：trace_id 为 32 位十六进制（W3C trace_id 格式），
span_id 为 16 位十六进制（W3C span_id 格式）。
"""
import contextvars
import uuid

_trace_id_var: contextvars.ContextVar = contextvars.ContextVar("trace_id", default=None)
_span_id_var: contextvars.ContextVar = contextvars.ContextVar("span_id", default=None)


def new_trace_id() -> str:
    """生成 W3C 格式 trace_id（32 hex）。"""
    return uuid.uuid4().hex


def new_span_id() -> str:
    """生成 W3C 格式 span_id（16 hex）。"""
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    """当前上下文的 trace_id；无则生成一个新的（不写入 context）。"""
    return _trace_id_var.get() or new_trace_id()


def get_span_id() -> str:
    return _span_id_var.get() or new_span_id()


def set_trace_context(trace_id: str = None, span_id: str = None):
    """设置当前 trace/span 上下文，返回 token 供 reset。"""
    if trace_id is None:
        trace_id = new_trace_id()
    if span_id is None:
        span_id = new_span_id()
    t = _trace_id_var.set(trace_id)
    s = _span_id_var.set(span_id)
    return (t, s)


def reset_trace_context(token) -> None:
    """退出上下文（在 finally 中调用）。"""
    _trace_id_var.reset(token[0])
    _span_id_var.reset(token[1])


def traceparent() -> str:
    """返回 W3C ``traceparent`` 头值： ``00-{trace_id}-{span_id}-01``。"""
    return f"00-{get_trace_id()}-{get_span_id()}-01"
