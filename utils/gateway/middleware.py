"""
API 网关中间件
=============

职责：
  1. 请求入口日志记录
  2. 限流检查（调用 DRF throttle 或独立检查）
  3. 响应头注入限流信息 (X-RateLimit-*)
  4. 429 拦截并返回统一 JSON

中间件链位置：
  MIDDLEWARE = [
      ...
      'django.contrib.auth.middleware.AuthenticationMiddleware',  ← 用户已注入
      'utils.gateway.middleware.GatewayMiddleware',                ← 此处
      'saas.middleware.TenantMiddleware',                          ← 租户上下文
      ...
  ]

注意：需要放在 AuthenticationMiddleware 之后（需要 request.user），
           在 TenantMiddleware 之前（租户限流需要租户上下文，但也可降级）。
"""

import time
import json
from typing import Callable

from django.http import JsonResponse
from loguru import logger

from utils.gateway.throttle import (
    _get_client_ip,
    check_sliding_window,
    get_gateway_config,
    REDIS_KEY_PREFIX,
)


# ─────────────────────────────────────────────────────────────
# 网关中间件
# ─────────────────────────────────────────────────────────────

class GatewayMiddleware:
    """
    API 网关中间件。

    对 /api/ 和 /saas/api/ 前缀的请求执行：
      - 请求日志
      - IP 级别限流
      - 注入响应头
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        # 前置处理
        self._process_request(request)

        # 获取响应
        response = self.get_response(request)

        # 后置处理
        self._process_response(request, response)

        return response

    # ── 请求前置处理 ────────────────────────────────

    def _process_request(self, request):
        """请求前置处理：日志 + IP 限流"""
        path = request.path if hasattr(request, 'path') else ''

        # 只对 API 路径限流
        if not self._is_api_path(path):
            return

        # 请求日志
        self._log_request(request, path)

        # IP 级别限流（中间件层快速拦截）
        if self._should_throttle(path):
            self._check_ip_rate(request, path)

    def _is_api_path(self, path: str) -> bool:
        """判断是否为 API 路径"""
        return path.startswith("/api/") or path.startswith("/saas/api/")

    def _should_throttle(self, path: str) -> bool:
        """判断路径是否需要限流（排除健康检查等）"""
        exclude_patterns = [
            "/api/health/",
            "/api/schema/",
            "/api/swagger/",
            "/api/redoc/",
        ]
        for pattern in exclude_patterns:
            if path.startswith(pattern):
                return False
        return True

    def _log_request(self, request, path: str):
        """记录 API 请求日志"""
        ip = _get_client_ip(request)
        method = request.method if hasattr(request, 'method') else 'UNKNOWN'
        user = getattr(request, 'user', None)
        user_id = user.pk if user and user.is_authenticated else 'anonymous'
        logger.debug(
            f"[Gateway] {method} {path} | IP={ip} | User={user_id}"
        )

    def _check_ip_rate(self, request, path: str):
        """
        IP 级别限流（中间件层快速检查）。

        注意：这会在 DRF throttle 检查之外再做一层独立检查。
        DRF throttle 由 throttle_classes 配置处理，
        这里提供更早的拦截点。
        """
        ip = _get_client_ip(request)
        limit, window = get_gateway_config.get_rate_for_request(request, "ip")

        key = f"{REDIS_KEY_PREFIX}mw:ip:{ip}"
        allowed, remaining, reset_in = check_sliding_window(key, limit, window)

        # 存储限流信息供响应头注入
        request._gateway_throttle_info = request._gateway_throttle_info if hasattr(request, '_gateway_throttle_info') else {}
        request._gateway_throttle_info.update({
            "mw_ip_limit": limit,
            "mw_ip_remaining": remaining,
            "mw_ip_reset": reset_in,
            "mw_ip_allowed": allowed,
        })

        # 如果中间件层 IP 限流触发，标记但不拦截（留给 DRF throttle 最终决定）
        if not allowed:
            logger.warning(
                f"[Gateway] MW IP 限流触发: {ip} → {path} "
                f"(limit={limit}/{window}s)"
            )

    # ── 响应后置处理 ────────────────────────────────

    def _process_response(self, request, response):
        """注入限流响应头"""
        path = request.path if hasattr(request, 'path') else ''

        if not self._is_api_path(path):
            return response

        # 注入通用网关头
        response["X-Gateway"] = "WorkBuddy-Gateway/1.0"
        response["X-Request-Path"] = path

        # 注入限流信息头
        throttle_info = getattr(request, '_gateway_throttle_info', {})
        if throttle_info:
            ttype = throttle_info.get("type", "ip")
            limit = throttle_info.get("limit", 0)
            remaining = throttle_info.get("remaining", 0)
            reset_in = throttle_info.get("reset_in", 60)

            response["X-RateLimit-Type"] = ttype
            response["X-RateLimit-Limit"] = str(limit)
            response["X-RateLimit-Remaining"] = str(remaining)
            response["X-RateLimit-Reset"] = str(int(time.time() + reset_in))

        return response

    # ── 异常处理 ────────────────────────────────────

    def process_exception(self, request, exception):
        """
        捕获 429（限流）异常，返回统一 JSON。

        DRF 的 Throttled 异常由 DRF exception_handler 处理，
        这里处理非 DRF 路由的限流异常。
        """
        from rest_framework.exceptions import Throttled as ThrottledException
        if isinstance(exception, ThrottledException):
            wait = getattr(exception, 'wait', 60)
            body = {
                "code": 429,
                "msg": f"请求过于频繁，请 {int(wait)} 秒后重试",
                "data": {
                    "retry_after": int(wait),
                    "detail": str(exception),
                },
            }
            response = JsonResponse(body, status=429)
            response["Retry-After"] = str(int(wait))
            response["X-RateLimit-Reset"] = str(int(time.time() + wait))
            return response

        return None
