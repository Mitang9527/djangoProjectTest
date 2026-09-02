"""
操作日志中间件 — 无侵入记录业务写操作（POST/PUT/PATCH/DELETE），对齐参考项目 OperationLog。
仅记录以 /api/v1/ 开头的写操作，跳过日志端点（防自审计死循环）与登录/注册/改密（走 LoginLog）；
写 core.OperationLog（租户级）+ 下沉 loguru（保留 ELK/Loki 分析能力）；写库失败静默，try/finally 保证 500 也记录；
用户优先 request.user，否则解析 Bearer JWT claims（DRF 认证在视图内，中间件拿不到 request.user）。
settings 启用须置于 TenantMiddleware 之后（其注入 request.tenant_id）。
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional, Tuple

from django.http import HttpRequest, HttpResponse
from loguru import logger

# API 请求日志使用专用 logger → api-{date}.log
from framework.log_utils import api_logger
from system.core.audit import set_current_request, get_client_ip


# 只记录写操作（读操作由网关/访问日志覆盖）
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 只记录业务 API 前缀
LOG_PATH_PREFIX = "/api/v1/"

# 跳过以下路径前缀（不写 OperationLog 表；登录类由 LoginLog 专项记录）
SKIP_PATH_PREFIXES = (
    "/api/v1/core/logs/",         # 日志查询端点自身，防自审计死循环
    "/api/v1/core/ping/",         # 健康探测
    "/api/v1/core/demo-login/",   # 演示登录（LoginLog 记录）
    "/api/v1/users/login/",       # 主登录（LoginLog 记录）
    "/api/v1/users/jwt/login/",   # 标准 JWT 登录（LoginLog 记录）
    "/api/v1/users/register/",    # 注册（含凭证，注册流程记录）
    "/api/v1/users/oidc/",        # OIDC 登录/回调（LoginLog 记录）
    "/api/v1/users/password/",    # 改密/重置等敏感凭证操作
)

# Authorization 头解析（Bearer <token>）
_AUTH_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)

# 请求方法 → 动作（对齐参考项目：DELETE→delete / PATCH→update / POST→create / PUT→update）
_ACTION_MAP = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# 请求摘要中跳过的敏感键（含子串匹配，防密码/令牌泄露进日志）
_SENSITIVE_KEY_SUBSTRINGS = ("password", "token", "secret", "api_key", "refresh")

_MAX_SUMMARY_LEN = 1000


class OperationLogMiddleware:
    """请求级操作日志中间件 — 写 OperationLog 表 + 下沉 loguru"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # 设置当前请求到线程本地存储，供审计系统使用
        set_current_request(request)

        if not self._should_log(request):
            try:
                return self.get_response(request)
            finally:
                set_current_request(None)

        # 坑：提前快照 JSON body——视图/DRF 解析后会消耗请求数据流，
        # 之后（_record 阶段）再读 request.body 会抛 RawPostDataException
        if "application/json" in request.META.get("CONTENT_TYPE", ""):
            try:
                request._oplog_body = request.body[: 64 * 1024]
            except Exception:  # noqa: BLE001
                request._oplog_body = b""

        start = time.perf_counter()
        response = None
        try:
            response = self.get_response(request)
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            # 异常隔离：记录失败不影响响应；try/finally 保证 500 异常也记录
            try:
                self._record(request, response, elapsed_ms)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[OPLOG] 操作日志写入失败(静默): {e}")
            finally:
                set_current_request(None)

    # 内部方法

    def _should_log(self, request: HttpRequest) -> bool:
        """判断是否需要记录: 写方法 + 业务 API 前缀 + 非跳过路径"""
        if request.method not in WRITE_METHODS:
            return False
        path = request.path
        if not path.startswith(LOG_PATH_PREFIX):
            return False
        return not any(path.startswith(p) for p in SKIP_PATH_PREFIXES)

    def _record(self, request: HttpRequest, response: Optional[HttpResponse], elapsed_ms: int) -> None:
        """写 OperationLog 表 + 下沉 loguru（失败由调用方静默）"""
        from django.apps import apps

        OperationLog = apps.get_model("core", "OperationLog")

        user, email, tenant_id = self._resolve_context(request)
        module, action = self._derive_module_action(request)
        status_code = response.status_code if response is not None else 500

        OperationLog.objects.create(
            tenant_id=tenant_id,
            user=user,
            email=email,
            module=module,
            action=action,
            method=request.method,
            path=request.path[:500],
            status_code=status_code,
            duration_ms=elapsed_ms,
            ip=get_client_ip(request) or "",
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            request_summary=self._request_summary(request),
        )

        # 下沉 loguru（保留 ELK/Loki 分析能力）
        self._record_to_loguru(request, status_code, elapsed_ms, email, module, action)

    def _resolve_context(self, request: HttpRequest) -> Tuple[Optional[object], str, Optional[str]]:
        """解析 (user, email, tenant_id)，失败兜底 (None, '', None)。
        user: request.user（会话认证）→ JWT claims user_id（DB 回查）→ None；
        tenant_id: request.tenant_id（TenantMiddleware 已按 X-Tenant-Id/JWT/session 解析）→ JWT claims tenant_id → None。"""
        tenant_id = getattr(request, "tenant_id", None)
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            user = None

        payload = self._parse_jwt_payload(request)

        if user is None and payload:
            uid = payload.get("user_id")
            if uid:
                try:
                    from django.contrib.auth import get_user_model
                    user = get_user_model().objects.filter(pk=uid).first()
                except Exception:  # noqa: BLE001
                    user = None
            if tenant_id is None:
                tenant_id = payload.get("tenant_id")

        email = user.email if (user and getattr(user, "email", None)) else ""
        if not email and payload:
            email = payload.get("email", "") or ""
        # 兜底：无邮箱时用用户名作为账号标识（与 record_login_log 口径一致）
        if not email and user is not None:
            email = getattr(user, "username", "") or ""
        return user, email, tenant_id

    def _parse_jwt_payload(self, request: HttpRequest) -> Optional[dict]:
        """解析 Authorization Bearer JWT 的 claims（仅用于日志归属；校验失败返回 None）"""
        header = request.META.get("HTTP_AUTHORIZATION", "")
        m = _AUTH_RE.match(header)
        if not m:
            return None
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            return AccessToken(m.group(1)).payload
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _derive_module_action(request: HttpRequest) -> Tuple[str, str]:
        """推导 module/action：module=去掉 /api/v1/ 后路径首段（如 /saas/departments/ → 'saas'）；
        action=DELETE→delete / PATCH→update / POST→create / PUT→update。"""
        rest = request.path[len(LOG_PATH_PREFIX):]
        module = rest.split("/", 1)[0] if rest else ""
        action = _ACTION_MAP.get(request.method, request.method.lower())
        return module[:100], action

    @staticmethod
    def _request_summary(request: HttpRequest) -> str:
        """请求摘要（脱敏）：仅记录 JSON body 的非敏感标量键；非 JSON/解析失败返回空串。
        用视图执行前快照的 _oplog_body（视图消费数据流后 request.body 不可再读）。"""
        content_type = request.META.get("CONTENT_TYPE", "")
        if "application/json" not in content_type:
            return ""
        body = getattr(request, "_oplog_body", None)
        if body is None:
            body = getattr(request, "body", None) or b""
        if not body:
            return ""
        try:
            data = json.loads(body[: 64 * 1024] or b"{}")
        except Exception:  # noqa: BLE001
            return ""
        if not isinstance(data, dict):
            return ""
        safe = {}
        for k, v in data.items():
            kl = k.lower()
            if any(s in kl for s in _SENSITIVE_KEY_SUBSTRINGS):
                continue
            if isinstance(v, (dict, list)):
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                safe[k] = v
        try:
            return json.dumps(safe, ensure_ascii=False)[:_MAX_SUMMARY_LEN]
        except Exception:  # noqa: BLE001
            return ""

    def _record_to_loguru(self, request: HttpRequest, status_code: int,
                          elapsed_ms: int, email: str, module: str, action: str) -> None:
        """写入 loguru（保留 ELK/Loki 分析能力）。坑：消息体含 {..} 会被当格式模板二次解析（见历史修复），
        结构化字段一律走 bind 进 extra，文本消息用无花括号可读串。"""
        log_data = {
            "user": email or "anonymous",
            "ip": get_client_ip(request) or "unknown",
            "method": request.method,
            "path": request.path,
            "status": status_code,
            "elapsed_ms": elapsed_ms,
            "module": module,
            "action": action,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
        }
        access_logger = api_logger.bind(**log_data)

        text = (
            f"[OPLOG] {request.method} {request.path} -> "
            f"{status_code} ({elapsed_ms}ms) module={module} action={action} user={email or 'anonymous'}"
        )
        if status_code >= 400:
            access_logger.warning(text)
        else:
            access_logger.info(text)
