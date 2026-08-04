"""DRF 集成：IdempotencyKeyMixin

使用::

    from framework.idempotency.drf import IdempotencyKeyMixin

    class OrderViewSet(IdempotencyKeyMixin, viewsets.ModelViewSet):
        idempotency_ttl = 600
        idempotency_key_header = "HTTP_IDEMPOTENCY_KEY"  # 默认
        idempotency_methods = ("POST", "PUT", "PATCH", "DELETE")
        idempotency_response_cache = True  # 缓存响应

请求头::

    Idempotency-Key: <unique-string>

如果 header 缺失 → 放行，不做幂等处理（由业务自行决定 key 来源）
"""
from __future__ import annotations

import functools
import json
from typing import Optional

from rest_framework.response import Response

from .core import idempotent_context


def _make_drf_fingerprint(request) -> str:
    """生成 DRF 请求指纹（method + path + body + query）"""
    body = getattr(request, "_body", b"") or b""
    try:
        body_text = body.decode("utf-8", errors="ignore")
    except Exception:
        body_text = repr(body)
    payload = {
        "method": request.method,
        "path": request.path,
        "query": dict(request.query_params),
        "body": body_text,
    }
    import hashlib
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _serialize_response(response: Response):
    try:
        return {
            "status_code": response.status_code,
            "data": response.data,
            "headers": dict(response.headers) if hasattr(response, "headers") else {},
        }
    except Exception:
        return {"status_code": response.status_code, "data": str(response.data)}


def _restore_response(payload):
    return Response(payload.get("data"), status=payload.get("status_code", 200))


class IdempotencyKeyMixin:
    """DRF ViewSet / APIView 幂等混入

    需在 settings.REST_FRAMEWORK 配置的 DEFAULT_AUTHENTICATION_CLASSES 之后使用
    """
    idempotency_ttl: int = 600
    idempotency_key_header: str = "HTTP_IDEMPOTENCY_KEY"   # request.META key
    idempotency_methods: tuple = ("POST", "PUT", "PATCH", "DELETE")
    idempotency_response_cache: bool = True
    idempotency_scope: str = "global"                       # 预留多租户

    def initial(self, request, *args, **kwargs):
        # 在 DRF 跑认证/权限之前判断是否要走幂等分支
        key = self._get_idempotency_key(request)
        method = request.method.upper()

        if key and method in self.idempotency_methods:
            fingerprint = _make_drf_fingerprint(request)
            scope = f"{self.idempotency_scope}:{self._get_tenant_id(request)}"
            full_key = f"{scope}:{method}:{key}"

            self._idemp_ctx = idempotent_context(
                key=full_key,
                fingerprint=fingerprint,
                ttl=self.idempotency_ttl,
            )
            self._idemp_ctx.__enter__()

            if self._idemp_ctx.is_replay:
                payload = self._idemp_ctx.replayed_response
                self._idemp_replay = _restore_response(payload) if payload else None

        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if getattr(self, "_idemp_replay", None) is not None:
            # 命中重放：用缓存响应替换
            response = self._idemp_replay
            response["X-Idempotency-Replay"] = "true"
        elif getattr(self, "_idemp_ctx", None) is not None and self.idempotency_response_cache:
            try:
                self._idemp_ctx.store(_serialize_response(response))
            except Exception:
                pass
        return response

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            ctx = getattr(self, "_idemp_ctx", None)
            if ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass
                self._idemp_ctx = None

    # ---------- helpers ----------
    def _get_idempotency_key(self, request) -> Optional[str]:
        return request.META.get(self.idempotency_key_header)

    def _get_tenant_id(self, request) -> str:
        # 兼容多租户：从 request.tenant / session / header 取
        tenant = getattr(request, "tenant", None)
        if tenant is not None:
            return str(getattr(tenant, "id", tenant))
        return request.META.get("HTTP_X_TENANT_ID", "default")
