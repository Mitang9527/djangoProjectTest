# sync-init: skip
"""
拦截器（Interceptor）
====================

拦截器协议允许你在 HTTP 请求生命周期的 3 个点插入自定义逻辑：

- ``before_request(method, url, **kwargs) -> dict``
  在请求发出前被调用，可**改写 kwargs**（headers / params / json / timeout 等）。
  返回 ``None`` 或原 ``kwargs`` 表示不改写。

- ``after_response(method, url, response, elapsed_ms) -> None``
  在收到响应后被调用（无论 2xx 还是 4xx/5xx），典型用途：日志、metrics、tracing。

- ``on_error(method, url, exception, elapsed_ms) -> None``
  在请求抛异常时调用（如网络错误、StatusError），**仅用于观测，不要重抛**（外层已统一处理）。

拦截器按 ``HTTPClient(interceptors=[...])`` 的**列表顺序**执行；
``before_request`` 链上**前一个的返回值是后一个的输入**。

内置拦截器
----------

- :class:`LoggingInterceptor`  —— loguru 绑定 trace_id/method/url/status/elapsed_ms
- :class:`TimingInterceptor`  —— 写 metrics（hits/latency_p95/status_codes）
- :class:`AuthInterceptor`    —— 自动加 Bearer Token，token 回调懒求值
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable


# ============================================================
# 协议
# ============================================================


@runtime_checkable
class Interceptor(Protocol):
    """拦截器协议（鸭子类型，可不显式继承）。"""

    def before_request(
        self, method: str, url: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        ...

    def after_response(
        self,
        method: str,
        url: str,
        response: Any,
        elapsed_ms: float,
    ) -> None:
        ...

    def on_error(
        self,
        method: str,
        url: str,
        exception: BaseException,
        elapsed_ms: float,
    ) -> None:
        ...


# ============================================================
# 内置：Logging
# ============================================================


class LoggingInterceptor:
    """loguru 上下文日志拦截器。

    绑定字段：``trace_id / method / url / status / elapsed_ms``。
    可选 ``slow_threshold_ms`` 超过此值记 WARNING。
    """

    def __init__(self, *, slow_threshold_ms: float = 1500.0, logger_name: str = "http") -> None:
        self.slow_threshold_ms = slow_threshold_ms
        self.logger_name = logger_name

    def _logger(self):  # 延迟 import 避免循环
        from loguru import logger
        return logger.bind(component=self.logger_name)

    def before_request(
        self, method: str, url: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        # 注入 trace_id（如果上层没传）
        headers = dict(kwargs.get("headers") or {})
        if "X-Trace-Id" not in headers and "x-trace-id" not in {k.lower() for k in headers}:
            headers["X-Trace-Id"] = uuid.uuid4().hex[:16]
            kwargs["headers"] = headers
        return kwargs

    def after_response(
        self,
        method: str,
        url: str,
        response: Any,
        elapsed_ms: float,
    ) -> None:
        level = "WARNING" if elapsed_ms > self.slow_threshold_ms else "INFO"
        log = self._logger()
        getattr(log, level.lower())(
            f"{method} {url} -> {response.status_code} ({elapsed_ms:.1f}ms)"
        )

    def on_error(
        self,
        method: str,
        url: str,
        exception: BaseException,
        elapsed_ms: float,
    ) -> None:
        self._logger().error(
            f"{method} {url} FAILED ({elapsed_ms:.1f}ms): "
            f"{type(exception).__name__}: {exception}"
        )


# ============================================================
# 内置：Timing
# ============================================================


class TimingInterceptor:
    """把每次请求的耗时与状态码喂给回调（用于接 Prometheus / 自家 metrics）。

    回调签名 ``callback(metrics: dict)``，其中
    ``metrics = {"method", "url", "status", "elapsed_ms", "ok"}``。
    """

    def __init__(
        self,
        *,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.callback = callback
        self._records: list[Dict[str, Any]] = []  # 内存版：方便测试 / 单 client 调试

    def after_response(
        self,
        method: str,
        url: str,
        response: Any,
        elapsed_ms: float,
    ) -> None:
        rec = {
            "method": method,
            "url": url,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "ok": True,
        }
        self._records.append(rec)
        if self.callback:
            try:
                self.callback(rec)
            except Exception:  # pragma: no cover
                pass

    def on_error(
        self,
        method: str,
        url: str,
        exception: BaseException,
        elapsed_ms: float,
    ) -> None:
        rec = {
            "method": method,
            "url": url,
            "status": getattr(exception, "status_code", 0),
            "elapsed_ms": elapsed_ms,
            "ok": False,
            "error": type(exception).__name__,
        }
        self._records.append(rec)
        if self.callback:
            try:
                self.callback(rec)
            except Exception:  # pragma: no cover
                pass

    # 便捷查询
    @property
    def count(self) -> int:
        return len(self._records)

    def avg_ms(self) -> float:
        return sum(r["elapsed_ms"] for r in self._records) / self.count if self._records else 0.0

    def p95_ms(self) -> float:
        if not self._records:
            return 0.0
        s = sorted(r["elapsed_ms"] for r in self._records)
        idx = max(0, int(round(0.95 * (len(s) - 1))))
        return s[idx]

    def reset(self) -> None:
        self._records.clear()


# ============================================================
# 内置：Auth
# ============================================================


class AuthInterceptor:
    """自动添加 ``Authorization: Bearer <token>``。

    ``token_getter`` 是回调（不接实参），**懒求值**：每次请求都重新调用，
    避免 token 过期仍复用旧值。token_getter 抛错时不抛给上层，仅记 WARNING。
    """

    HEADER = "Authorization"

    def __init__(
        self,
        token_getter: Callable[[], str],
        *,
        scheme: str = "Bearer",
    ) -> None:
        self.token_getter = token_getter
        self.scheme = scheme

    def before_request(
        self, method: str, url: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        try:
            token = self.token_getter()
        except Exception as e:
            from loguru import logger
            logger.warning(f"AuthInterceptor: token_getter raised {type(e).__name__}: {e}")
            return None
        if not token:
            return None
        headers = dict(kwargs.get("headers") or {})
        headers[self.HEADER] = f"{self.scheme} {token}"
        kwargs["headers"] = headers
        return kwargs


__all__ = [
    "Interceptor",
    "LoggingInterceptor",
    "TimingInterceptor",
    "AuthInterceptor",
]
