# sync-init: skip
"""
utils.http_client
=================

企业级 ``requests`` 封装：

- :class:`HTTPClient`  —— 主类（Session 池 + 自动重试 + 拦截器 + 统一异常）
- :mod:`.exceptions`   —— 统一异常（HTTPError / TimeoutError / StatusError / RetryExhaustedError ...）
- :mod:`.interceptors` —— 拦截器协议 + 3 个内置（Logging / Timing / Auth）

零新增依赖：仅依赖项目已有的 ``requests`` + ``loguru``。

Examples
--------

>>> from utils.http_client import HTTPClient, default_client

>>> client = HTTPClient(base_url="https://api.example.com", max_retries=3)
>>> resp = client.get("/users/1")
>>> resp.raise_for_status()
>>> data = resp.json()

>>> with HTTPClient(base_url="...") as c:
...     c.post("/login", json={"u": "x"})

>>> default_client.get("https://httpbin.org/ip")
"""
# sync-init: skip

from .exceptions import (
    HTTPError,
    HTTPClientError,
    InvalidConfigError,
    InterceptorError,
    HTTPNetworkError,
    TimeoutError,
    ConnectionError_,
    StatusError,
    RetryExhaustedError,
)
from .interceptors import (
    Interceptor,
    LoggingInterceptor,
    TimingInterceptor,
    AuthInterceptor,
)
from .client import (
    HTTPClient,
    default_client,
    get_default_client,
    set_default_client,
    close_default_client,
    TimeoutSpec,
)

__all__ = [
    # client
    "HTTPClient",
    "default_client",
    "get_default_client",
    "set_default_client",
    "close_default_client",
    "TimeoutSpec",
    # exceptions
    "HTTPError",
    "HTTPClientError",
    "InvalidConfigError",
    "InterceptorError",
    "HTTPNetworkError",
    "TimeoutError",
    "ConnectionError_",
    "StatusError",
    "RetryExhaustedError",
    # interceptors
    "Interceptor",
    "LoggingInterceptor",
    "TimingInterceptor",
    "AuthInterceptor",
]
