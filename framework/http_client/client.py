# sync-init: skip
"""HTTPClient：requests.Session 的企业级封装（连接池复用/指数退避重试/拦截器链/统一超时/异常包装）。"""
from __future__ import annotations

import random
import threading
import time
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    HTTPError,
    HTTPNetworkError,
    StatusError,
    TimeoutError,
    ConnectionError_,
    RetryExhaustedError,
    InterceptorError,
)
from .interceptors import Interceptor, LoggingInterceptor

TimeoutSpec = Union[None, float, Tuple[float, float]]  # None / 单一值 / (connect, read)


class HTTPClient:
    """通用 HTTP 客户端（基于 requests.Session）。

    参数: base_url(留空则需传完整URL)/timeout(默认(5,30))/max_retries(0=不重试,默认3)
    backoff_factor(第N次等待 base*2**(N-1)+jitter)/retry_on_status(默认429,500,502,503,504)
    pool_connections(默认10)/pool_maxsize(默认20)/headers/interceptors(按序执行)/verify_ssl(默认True)/raise_for_status(默认True)
    """

    DEFAULT_TIMEOUT: TimeoutSpec = (5, 30)
    DEFAULT_RETRY_STATUS: Tuple[int, ...] = (429, 500, 502, 503, 504)
    DEFAULT_RETRY_METHODS: Tuple[str, ...] = ("HEAD", "GET", "PUT", "DELETE", "OPTIONS", "POST", "PATCH")

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: TimeoutSpec = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        retry_on_status: Tuple[int, ...] = DEFAULT_RETRY_STATUS,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
        headers: Optional[Dict[str, str]] = None,
        interceptors: Optional[List[Interceptor]] = None,
        verify_ssl: bool = True,
        raise_for_status: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_factor = backoff_factor
        self.retry_on_status = tuple(retry_on_status)
        self.raise_for_status = raise_for_status

        # session
        self._session = requests.Session()
        if headers:
            self._session.headers.update(headers)

        # 适配器（连接池 + urllib3 Retry）
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=Retry(
                total=max_retries,
                backoff_factor=backoff_factor,
                status_forcelist=list(retry_on_status),
                allowed_methods=list(self.DEFAULT_RETRY_METHODS),
                raise_on_status=False,
            ),
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.verify = verify_ssl

        # 拦截器链
        self.interceptors: List[Interceptor] = list(interceptors) if interceptors else [LoggingInterceptor()]

        # 锁：拦截器链非线程安全
        self._lock = threading.RLock()

    def __enter__(self) -> "HTTPClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def _build_url(self, path: str) -> str:
        if not path:
            return self.base_url
        if path.startswith(("http://", "https://")):
            return path
        if self.base_url:
            return f"{self.base_url}/{path.lstrip('/')}"
        return path

    def get(self, path: str, *, params: Any = None, headers: Any = None,
            timeout: TimeoutSpec = None, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, params=params, headers=headers, timeout=timeout, **kwargs)

    def post(self, path: str, *, json: Any = None, data: Any = None, headers: Any = None,
             timeout: TimeoutSpec = None, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, json=json, data=data, headers=headers, timeout=timeout, **kwargs)

    def put(self, path: str, *, json: Any = None, data: Any = None, headers: Any = None,
            timeout: TimeoutSpec = None, **kwargs: Any) -> requests.Response:
        return self.request("PUT", path, json=json, data=data, headers=headers, timeout=timeout, **kwargs)

    def patch(self, path: str, *, json: Any = None, data: Any = None, headers: Any = None,
              timeout: TimeoutSpec = None, **kwargs: Any) -> requests.Response:
        return self.request("PATCH", path, json=json, data=data, headers=headers, timeout=timeout, **kwargs)

    def delete(self, path: str, *, params: Any = None, headers: Any = None,
               timeout: TimeoutSpec = None, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", path, params=params, headers=headers, timeout=timeout, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """发起一次 HTTP 请求（含重试 + 拦截器 + 异常包装）。

        :param method: HTTP 方法；url: 路径或完整 URL
        :param kwargs: 透传 requests.Session.request（params/json/data/headers/files/timeout/cookies/auth）
        :return: requests.Response；raise_for_status=True（默认）时非 2xx 抛 StatusError
        :raises StatusError/TimeoutError/ConnectionError_/RetryExhaustedError
        """
        method = method.upper()
        full_url = self._build_url(url)

        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.timeout

        # 拦截器：before_request 链式改写 kwargs
        kwargs = self._run_before(method, full_url, kwargs)

        # 应用层重试（适配器层 urllib3 Retry 已做一次；与拦截器协调更灵活）
        last_exc: Optional[BaseException] = None
        total_attempts = self.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            t0 = time.perf_counter()
            try:
                response = self._session.request(method, full_url, **kwargs)
            except requests.Timeout as e:
                last_exc = TimeoutError(str(e))
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._run_on_error(method, full_url, last_exc, elapsed_ms)
                if attempt >= total_attempts:
                    break
                self._sleep_backoff(attempt)
                continue
            except requests.ConnectionError as e:
                last_exc = ConnectionError_(str(e))
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._run_on_error(method, full_url, last_exc, elapsed_ms)
                if attempt >= total_attempts:
                    break
                self._sleep_backoff(attempt)
                continue
            except requests.RequestException as e:
                # 其他 requests 异常：包成 HTTPNetworkError
                last_exc = HTTPNetworkError(str(e))
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._run_on_error(method, full_url, last_exc, elapsed_ms)
                if attempt >= total_attempts:
                    break
                self._sleep_backoff(attempt)
                continue

            elapsed_ms = (time.perf_counter() - t0) * 1000

            if 200 <= response.status_code < 300:
                self._run_after(method, full_url, response, elapsed_ms)
                return response

            # 4xx / 5xx —— 构造 StatusError（不一定抛出，存到 last_exc）
            status_err = StatusError(
                f"HTTP {response.status_code} {method} {full_url}",
                status_code=response.status_code,
                url=full_url,
                method=method,
                body=response.text[:500],
                response=response,
            )
            # raise_for_status=False：不做任何重试/异常处理，直接返回 response
            if not self.raise_for_status:
                self._run_after(method, full_url, response, elapsed_ms)
                return response
            is_retryable = response.status_code in self.retry_on_status
            if is_retryable and attempt < total_attempts:
                # 中间失败：通知 on_error，休眠，继续
                last_exc = status_err
                self._run_on_error(method, full_url, last_exc, elapsed_ms)
                self._sleep_backoff(attempt)
                continue

            # 不重试 / 4xx（不可重试状态）/ 最后一次仍然失败
            last_exc = status_err
            if is_retryable and attempt >= total_attempts:
                # 重试耗尽：包成 RetryExhaustedError（on_error 已发 N-1 次，最后一次仍发）
                self._run_on_error(method, full_url, last_exc, elapsed_ms)
                raise RetryExhaustedError(
                    f"Retry exhausted after {total_attempts} attempts: "
                    f"{type(last_exc).__name__}: {last_exc}",
                    attempts=total_attempts,
                    last_error=last_exc,
                )

            # 不可重试（4xx 等）：走 after_response + raise_for_status
            self._run_after(method, full_url, response, elapsed_ms)
            raise status_err

        # 走到这里说明网络异常重试用尽
        assert last_exc is not None
        # max_retries=0 意味着"没重试"，直接抛原始异常，不要包成 RetryExhausted
        if self.max_retries == 0:
            raise last_exc
        raise RetryExhaustedError(
            f"Retry exhausted after {total_attempts} attempts: "
            f"{type(last_exc).__name__}: {last_exc}",
            attempts=total_attempts,
            last_error=last_exc,
        )

    def _run_before(self, method: str, url: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            for interceptor in self.interceptors:
                try:
                    new_kwargs = interceptor.before_request(method, url, **kwargs)
                except Exception as e:
                    raise InterceptorError(
                        f"{type(interceptor).__name__}.before_request raised: {e}"
                    ) from e
                if new_kwargs is not None:
                    kwargs = new_kwargs
        return kwargs

    def _run_after(
        self,
        method: str,
        url: str,
        response: requests.Response,
        elapsed_ms: float,
    ) -> None:
        with self._lock:
            for interceptor in self.interceptors:
                with suppress(Exception):
                    interceptor.after_response(method, url, response, elapsed_ms)

    def _run_on_error(
        self,
        method: str,
        url: str,
        exc: BaseException,
        elapsed_ms: float,
    ) -> None:
        with self._lock:
            for interceptor in self.interceptors:
                with suppress(Exception):
                    interceptor.on_error(method, url, exc, elapsed_ms)

    def _sleep_backoff(self, attempt: int) -> None:
        base = self.backoff_factor * (2 ** (attempt - 1))
        jitter = random.uniform(0, self.backoff_factor)
        time.sleep(base + jitter)

    @property
    def session(self) -> requests.Session:
        """暴露底层 ``requests.Session``，便于高级场景（如 ``session.get(...)``）。"""
        return self._session

    def add_interceptor(self, interceptor: Interceptor) -> "HTTPClient":
        """链式添加拦截器。"""
        with self._lock:
            self.interceptors.append(interceptor)
        return self

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"HTTPClient(base_url={self.base_url!r}, max_retries={self.max_retries}, "
            f"interceptors={len(self.interceptors)})"
        )


# 全局默认 client（懒创建，见 __getattr__ 兼容别名）
_default_client: Optional[HTTPClient] = None
_default_lock = threading.Lock()


def get_default_client() -> HTTPClient:
    """获取（或懒创建）全局默认 client。"""
    global _default_client
    if _default_client is None:
        with _default_lock:
            if _default_client is None:
                _default_client = HTTPClient()
    return _default_client


def set_default_client(client: HTTPClient) -> None:
    """覆盖全局默认 client。"""
    global _default_client
    with _default_lock:
        _default_client = client


def close_default_client() -> None:
    """关闭全局默认 client（仅在测试/进程退出时调用）。"""
    global _default_client
    with _default_lock:
        if _default_client is not None:
            _default_client.close()
        _default_client = None


# 兼容别名（更直观）
default_client = None  # type: ignore[assignment]


def __getattr__(name: str):  # PEP 562
    if name == "default_client":
        return get_default_client()
    raise AttributeError(f"module 'framework.http_client' has no attribute {name!r}")


__all__ = [
    "HTTPClient",
    "default_client",
    "get_default_client",
    "set_default_client",
    "close_default_client",
    "TimeoutSpec",
]
