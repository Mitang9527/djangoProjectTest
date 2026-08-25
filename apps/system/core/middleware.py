"""
操作日志中间件 — 无侵入记录所有 API 请求。

特性:
- 记录: 用户、IP、方法、路径、状态码、响应耗时、User-Agent
- 异步写入: 使用线程池避免阻塞请求 (或者: 使用 loguru + 离线分析)
- 异常隔离: 中间件异常不影响业务请求
- 可配置: 仅记录 /api/ 路径，跳过健康检查、静态文件

模式选择:
  MODE = "db"  → 写入 AuditLog 模型 (适合中小流量)
  MODE = "log" → 写入 loguru (适合高流量, 后续用 ELK/Loki 分析)

# settings.py 启用:
MIDDLEWARE = [
    ...
    'apps.system.core.middleware.OperationLogMiddleware',
]
"""

from __future__ import annotations

import time
import threading
from typing import Optional

from django.http import HttpRequest, HttpResponse
from loguru import logger

# API 请求日志使用专用 logger → api-{date}.log
from framework.log_utils import api_logger
from system.core.audit import set_current_request


# ---- 配置 ----

# 写入模式: "db" → AuditLog 模型; "log" → loguru
MODE = "log"

# 只记录以下路径前缀的请求 (空列表 = 记录所有)
LOG_PATH_PREFIXES = ["/api/", "/admin/"]

# 跳过以下路径
SKIP_PATHS = [
    "/api/health/",
    "/api/docs/",
    "/api/schema/",
    "/static/",
    "/media/",
    "/favicon.ico",
]

# 日志级别阈值 (只记录 >= 此状态码的请求, 0 = 全部)
MIN_STATUS_CODE = 0


# ---- 中间件 ----

class OperationLogMiddleware:
    """请求级操作日志中间件"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # 设置当前请求到线程本地存储，供审计系统使用
        set_current_request(request)
        
        # 判断是否需要记录
        if not self._should_log(request):
            response = self.get_response(request)
            set_current_request(None)
            return response

        start_time = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)

        # 异常隔离: 日志记录失败不影响响应
        try:
            self._record(request, response, elapsed_ms)
        except Exception:
            pass  # 静默失败
        
        # 清除当前请求
        set_current_request(None)

        return response

    # -----------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------

    def _should_log(self, request: HttpRequest) -> bool:
        """判断是否需要记录该请求"""
        path = request.path

        # 跳过不需要记录的路径
        for skip in SKIP_PATHS:
            if path.startswith(skip):
                return False

        # 如果配置了前缀过滤, 只记录匹配的
        if LOG_PATH_PREFIXES:
            return any(path.startswith(p) for p in LOG_PATH_PREFIXES)

        return True

    def _record(self, request: HttpRequest, response: HttpResponse, elapsed_ms: float) -> None:
        """记录日志 (根据 MODE 选择写入方式)"""
        if response.status_code < MIN_STATUS_CODE:
            return

        if MODE == "log":
            self._record_to_loguru(request, response, elapsed_ms)
        else:
            self._record_to_db(request, response, elapsed_ms)

    def _record_to_loguru(self, request: HttpRequest, response: HttpResponse, elapsed_ms: float) -> None:
        """写入 loguru (高性能, 推荐搭配 Loki/ELK)"""
        user_str = (
            request.user.username
            if request.user and request.user.is_authenticated
            else "anonymous"
        )

        log_data = {
            "user": user_str,
            "ip": self._get_client_ip(request),
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
        }

        # 关键修复: loguru 会把「消息正文」当成格式模板二次解析。
        # 若消息里包含 '{...}'(例如把 dict/list 直接 f-string 拼接进消息),
        # 其中的 'user' / 'method' 等会被误当作格式字段, 触发 KeyError: 'user'。
        # 因此:
        #   1) 结构化字段通过 bind 进入 extra —— JSON sink 仍会采集(便于 ELK/Loki 过滤);
        #   2) 文本消息改为「无花括号」的可读串, 彻底规避二次解析。
        access_logger = api_logger.bind(user=user_str, **log_data)

        text = (
            f"[ACCESS] {request.method} {request.path} -> "
            f"{response.status_code} ({elapsed_ms}ms) user={user_str}"
        )

        if response.status_code >= 400:
            access_logger.warning(text)
        else:
            access_logger.info(text)

    def _record_to_db(self, request: HttpRequest, response: HttpResponse, elapsed_ms: float) -> None:
        """写入 AuditLog 数据库模型 (异步)"""
        # 延迟导入, 避免模型尚未加载
        from django.apps import apps

        user = request.user if request.user.is_authenticated else None
        ip = self._get_client_ip(request)

        action_info = {
            "path": request.path,
            "method": request.method,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "query_string": request.META.get("QUERY_STRING", ""),
        }

        # 在线程池中异步写入 (避免阻塞请求)
        threading.Thread(
            target=self._write_audit_log,
            args=(user.id if user else None, ip, action_info, request.META.get("HTTP_USER_AGENT")),
            daemon=True,
        ).start()

    @staticmethod
    def _write_audit_log(user_id, ip, action_info, user_agent) -> None:
        """异步写入 (在独立线程中执行, 持有独立 DB 连接)"""
        from django.db import connections

        # 强制关闭当前线程的旧连接, 获取新连接
        for conn in connections.all():
            conn.close_if_unusable_or_obsolete()

        try:
            from django.apps import apps
            from django.contrib.auth import get_user_model

            AuditLog = apps.get_model("core", "AuditLog")
            User = get_user_model()

            user = User.objects.get(pk=user_id) if user_id else None

            AuditLog.objects.create(
                user=user,
                action="OTHER",
                target_model=action_info.get("path", ""),
                target_id=None,
                action_info=action_info,
                ip_address=ip,
                user_agent=(user_agent or "")[:500],
            )
        except Exception as e:
            # 即使异步写入失败也不要在主线程抛错
            logger.debug(f"[OPLOG] 异步写入审计日志失败: {e}")

    @staticmethod
    def _get_client_ip(request: HttpRequest) -> str:
        """获取客户端 IP (考虑反向代理)"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")
