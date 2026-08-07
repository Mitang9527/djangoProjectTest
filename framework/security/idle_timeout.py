"""
会话空闲超时中间件（Session Idle Timeout）。

与 Django 原生的 ``SESSION_COOKIE_AGE``（绝对过期：从登录那一刻起固定时长）不同，
本中间件实现"空闲即退"语义：

- 已认证用户的每次请求都会刷新 ``last_activity`` 时间戳；
- 若距上次活跃已超过 ``SESSION_IDLE_TIMEOUT_SECONDS`` 秒，则立即 ``flush`` 会话
  （销毁登录态），当前请求不再进入视图，直接返回 401（API）或重定向到登录页（页面）；
- 配置为 ``0`` 时禁用本逻辑（行为与之前一致）。

排除路径：健康检查、静态/媒体文件、登录页、OIDC 流程等，避免打断登录流程或被
监控探活请求干扰空闲计时。
"""
from __future__ import annotations

import time

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

# 兜底默认值：仅当 settings 未定义时使用（正常由 base.py 从 model.py 注入）
_DEFAULT_EXEMPT_PREFIXES = (
    "/api/health",
    "/static",
    "/media",
    "/admin/login",
    "/api/users/login",
    "/api/users/oidc",
    "/favicon.ico",
)
_DEFAULT_REDIRECT_URL = "/admin/login/"


def _is_api_request(request) -> bool:
    """API 请求判定：以 /api/ 开头，或显式 Accept application/json。"""
    if request.path.startswith("/api/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


class IdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = int(getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 0) or 0)
        # 排除路径与重定向地址均来自 settings（可经环境变量配置），并保留兜底默认值
        self.exempt_prefixes = tuple(
            getattr(settings, "SESSION_IDLE_TIMEOUT_EXEMPT_PATHS", _DEFAULT_EXEMPT_PREFIXES)
            or _DEFAULT_EXEMPT_PREFIXES
        )
        self.redirect_url = getattr(
            settings, "SESSION_IDLE_TIMEOUT_REDIRECT_URL", _DEFAULT_REDIRECT_URL
        ) or _DEFAULT_REDIRECT_URL

    def __call__(self, request):
        # 排除健康检查 / 静态 / 登录 / SSO 等路径（可配置）
        if any(request.path.startswith(p) for p in self.exempt_prefixes):
            return self.get_response(request)

        session = getattr(request, "session", None)
        user = getattr(request, "user", None)
        is_authenticated = bool(getattr(user, "is_authenticated", False))

        # 仅对已认证用户判定空闲超时
        if session is not None and is_authenticated:
            last = session.get("last_activity")
            if last is not None:
                try:
                    last = float(last)
                except (TypeError, ValueError):
                    last = None
                if last is not None and self.timeout > 0:
                    idle = time.time() - last
                    if idle > self.timeout:
                        # 空闲超时：销毁会话，立即拒绝当前请求
                        session.flush()
                        if _is_api_request(request):
                            return JsonResponse(
                                {"detail": "Session idle timeout, please login again."},
                                status=401,
                            )
                        return redirect(self.redirect_url)

            # 记录/刷新最后活跃时间（写入会触发 session.modified，响应时保存）
            session["last_activity"] = time.time()

        # 匿名用户或无需判定的请求：正常放行
        return self.get_response(request)
