# sync-init: skip
"""
异常体系
========

继承自 ``requests.exceptions`` 体系，**业务代码可以 ``except requests.exceptions.RequestException``
一把抓**所有 HTTP 相关错误，也可以精细化捕获。

层级
----

    HTTPError(Exception)
    ├── HTTPClientError(HTTPError)             # 客户端使用错误（配置不当等）
    │   ├── InvalidConfigError
    │   └── InterceptorError
    └── HTTPNetworkError(HTTPError)            # 运行时网络/HTTP 错误
        ├── TimeoutError                       # 对应 requests.Timeout
        ├── ConnectionError_                   # 对应 requests.ConnectionError
        ├── StatusError                        # HTTP 4xx/5xx（非 2xx 都算）
        └── RetryExhaustedError                # 重试次数耗尽
"""
from __future__ import annotations

from typing import Any, Optional


class HTTPError(Exception):
    """所有 HTTPClient 异常的基类。"""


# ============================================================
# 客户端使用错误（不重试，调用方应立即修代码/配置）
# ============================================================


class HTTPClientError(HTTPError):
    """客户端配置/使用错误（不会自动重试）。"""


class InvalidConfigError(HTTPClientError):
    """配置无效（如 base_url 格式错误、拦截器协议不正确）。"""


class InterceptorError(HTTPClientError):
    """拦截器内部抛出未处理异常时包装。"""


# ============================================================
# 运行时网络/HTTP 错误（按策略可能重试）
# ============================================================


class HTTPNetworkError(HTTPError):
    """运行时网络/HTTP 错误基类。"""


class TimeoutError(HTTPNetworkError):
    """请求超时。"""


class ConnectionError_(HTTPNetworkError):
    """网络连接失败（DNS/连接拒绝/SSL 等）。"""


class StatusError(HTTPNetworkError):
    """HTTP 状态码非 2xx。

    Attributes
    ----------
    status_code : int
    url : str
    method : str
    body : str
    response : requests.Response
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        url: str,
        method: str,
        body: str = "",
        response: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.method = method
        self.body = body
        self.response = response

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"StatusError(status={self.status_code}, method={self.method!r}, "
            f"url={self.url!r})"
        )


class RetryExhaustedError(HTTPNetworkError):
    """重试次数耗尽仍未成功。

    Attributes
    ----------
    attempts : int
    last_error : BaseException
    """

    def __init__(self, message: str, *, attempts: int, last_error: BaseException) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RetryExhaustedError(attempts={self.attempts}, "
            f"last_error={type(self.last_error).__name__}: {self.last_error})"
        )


__all__ = [
    "HTTPError",
    "HTTPClientError",
    "InvalidConfigError",
    "InterceptorError",
    "HTTPNetworkError",
    "TimeoutError",
    "ConnectionError_",
    "StatusError",
    "RetryExhaustedError",
]


# 兼容：requests 自身的 Timeout / ConnectionError 仍然可被 except 捕获
# （本模块的 TimeoutError/ConnectionError_ 是单独命名避免与 requests 同名冲突）
