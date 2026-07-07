# sync-init: skip
"""
版本管理 - 中间件
================

在请求到达视图前：
1) 探测版本（url / header / query）
2) 解析有效版本（应用灰度规则）
3) 把版本挂到 request.api_version
4) 把版本元信息写入响应头（Sunset / Deprecation / X-API-Version-*）
"""
from __future__ import annotations

import logging
from datetime import date

from django.http import HttpResponse, JsonResponse

from .config import VersioningConfig, detect_version_from_request
from .core import VersionStatus, get_registry

logger = logging.getLogger(__name__)


class VersioningMiddleware:
    """
    Django 中间件，注入 ``request.api_version`` 并在响应头标注版本信息。

    用法（在 settings.MIDDLEWARE 末尾追加）::

        MIDDLEWARE = [
            ...,
            "utils.versioning.middleware.VersioningMiddleware",
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._config: Optional[VersioningConfig] = None

    def _get_config(self) -> VersioningConfig:
        if self._config is None:
            self._config = VersioningConfig().get_from_settings()
        return self._config

    def __call__(self, request):
        cfg = self._get_config()
        registry = get_registry()

        # 1) 探测
        requested = detect_version_from_request(request, cfg)
        request.api_version = None

        # 2) 解析
        if requested:
            spec = registry.get(requested)
            if spec and spec.is_available():
                request.api_version = spec.name
            elif spec and spec.status == VersionStatus.SUNSET:
                return JsonResponse(
                    {
                        "detail": f"API 版本 {spec.name} 已停用",
                        "successor": spec.successor,
                    },
                    status=410,
                )
            elif spec and spec.status == VersionStatus.DISABLED:
                return JsonResponse(
                    {"detail": f"API 版本 {spec.name} 已禁用"},
                    status=404,
                )
            else:
                # 未知版本：放行至 fallback
                if not cfg.allow_fallback:
                    return JsonResponse(
                        {"detail": f"API 版本 {requested} 不存在"},
                        status=404,
                    )

        # 3) fallback
        if not request.api_version:
            default = registry.default()
            request.api_version = default.name if default else None

        # 4) 走视图
        response = self.get_response(request)

        # 5) 标注响应头
        if request.api_version:
            response["X-API-Version-Requested"] = requested or ""
            response["X-API-Version-Served"] = request.api_version
            spec = registry.get(request.api_version)
            if spec:
                if spec.is_deprecated() and spec.sunset_date:
                    response["Deprecation"] = spec.deprecated_at.isoformat() if isinstance(spec.deprecated_at, date) else "true"
                    response["Sunset"] = spec.sunset_date.isoformat()
                    if spec.successor:
                        response["Link"] = f'</api/{spec.successor}/>; rel="successor-version"'

        return response
