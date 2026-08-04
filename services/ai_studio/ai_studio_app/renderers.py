"""
统一 API 响应格式化渲染器（自包含副本，便于独立服务打包）。

确保所有 API 端点（成功/错误）都返回统一 JSON 结构:
{
  "status":  "success" | "error",
  "code":    200 | 400 | 500,
  "message": "操作成功" | "具体错误信息",
  "data":    { ... } | null,
  "errors":  { ... } | null
}

特性:
- 204 响应自动转为 200 (DELETE 返回统一结构)
- 字段级校验错误包装 (DRF serializer.errors)
- JWT Token 响应兼容 (access/refresh 结构保留在 data)
- 已包装结构不做二次包装 (幂等)
"""

from __future__ import annotations

from rest_framework.renderers import JSONRenderer


class CustomRenderer(JSONRenderer):
    """统一全局响应格式渲染器"""

    charset = "utf-8"
    media_type = "application/json"

    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"

    MSG_DEFAULT_SUCCESS = "操作成功"
    MSG_DEFAULT_ERROR = "请求处理失败"
    MSG_TOKEN_SUCCESS = "Token 获取成功"
    MSG_DELETE_SUCCESS = "删除操作成功完成"
    MSG_VALIDATION_ERROR = "请求参数有误或处理失败"
    MSG_UNKNOWN_ERROR = "发生未知错误"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        assert renderer_context is not None, "renderer_context 不能为空"
        assert "response" in renderer_context, "renderer_context 中缺少 response"

        response = renderer_context["response"]
        status_code = response.status_code
        request = renderer_context.get("request")

        # ---- 1. 204 No Content → 200 ----
        original_status = None
        if status_code == 204:
            original_status = 204
            response.status_code = 200
            status_code = 200
            data = None

        # ---- 2. 构建统一结构骨架 ----
        unified = {
            "status": self.STATUS_SUCCESS,
            "code": status_code,
            "message": self.MSG_DEFAULT_SUCCESS,
            "data": None,
            "errors": None,
        }

        # ---- 3. JWT 登录成功特殊处理 ----
        if self._is_jwt_success(data, status_code):
            unified["message"] = self.MSG_TOKEN_SUCCESS
            unified["data"] = data
            data = None  # 标记已处理

        # ---- 4. JWT 认证失败特殊处理 ----
        if self._is_jwt_error(data, status_code):
            unified["status"] = self.STATUS_ERROR
            unified["message"] = data.get("detail", "认证失败")
            unified["errors"] = {
                "token_error": data.get("detail"),
                "error_code": data.get("code"),
            }
            data = None  # 标记已处理

        # ---- 5. 通用包装 ----
        if data is not None:
            if status_code >= 400:
                self._wrap_error(unified, data, status_code)
            else:
                self._wrap_success(unified, data, status_code)

        # ---- 6. 兜底 message ----
        if not unified.get("message"):
            unified["message"] = self._fallback_message(unified["status"])

        # ---- 7. 清理冗余字段 ----
        if unified["status"] == self.STATUS_SUCCESS:
            unified["errors"] = None
        else:
            unified["data"] = None
            if unified.get("errors") is None:
                unified["errors"] = {"detail": unified.get("message", self.MSG_UNKNOWN_ERROR)}

        # ---- 8. 删除操作语义化 ----
        if original_status == 204 and unified["status"] == self.STATUS_SUCCESS:
            unified["message"] = self.MSG_DELETE_SUCCESS

        # ---- 9. i18n 翻译 (预留钩子) ----
        self._apply_i18n(unified, request)

        return super().render(unified, accepted_media_type, renderer_context)

    @staticmethod
    def _is_jwt_success(data, status_code: int) -> bool:
        return (
            isinstance(data, dict)
            and "access" in data
            and "refresh" in data
            and status_code == 200
        )

    @staticmethod
    def _is_jwt_error(data, status_code: int) -> bool:
        return (
            isinstance(data, dict)
            and "detail" in data
            and "code" in data
            and "messages" not in data
            and status_code >= 400
        )

    def _wrap_error(self, unified: dict, data, status_code: int) -> None:
        unified["status"] = self.STATUS_ERROR
        unified["data"] = None

        if isinstance(data, dict) and "detail" in data:
            unified["message"] = str(data.get("detail", self.MSG_DEFAULT_ERROR))
            unified["errors"] = {"detail": data.get("detail")}
        elif isinstance(data, (dict, list)):
            unified["message"] = self.MSG_VALIDATION_ERROR
            unified["errors"] = data
        else:
            unified["message"] = str(data)
            unified["errors"] = {"detail": str(data)}

    def _wrap_success(self, unified: dict, data, status_code: int) -> None:
        unified["status"] = self.STATUS_SUCCESS

        if isinstance(data, dict) and all(k in data for k in ("status", "code", "message")):
            original_code = unified["code"]
            unified.update(data)
            unified["code"] = original_code
            if "errors" not in data:
                unified["errors"] = None
            if "data" not in data:
                unified["data"] = data.get("data", None)
        else:
            unified["data"] = data
            unified["message"] = self.MSG_DEFAULT_SUCCESS

    def _fallback_message(self, status: str) -> str:
        if status == self.STATUS_SUCCESS:
            return self.MSG_DEFAULT_SUCCESS
        return self.MSG_UNKNOWN_ERROR

    def _apply_i18n(self, unified: dict, request) -> None:
        pass
