"""
版本管理工具包
==============

在 DRF 自带版本（``Accept: application/json; version=1.0``）之上，提供
**灰度发布 / 流量切分 / 多版本共存 / 自动降级**能力。

核心特性
--------

1. **多版本路由**：通过 URL 前缀 / Header / Subdomain 三种方式识别版本
2. **灰度发布**：按 ``Header X-User-Tier`` / ``Cookie`` / ``权重`` 路由到不同版本
3. **自动降级**：当新版接口未实现某方法时，自动 fallback 到旧版
4. **废弃提示**：过期版本在响应头 ``Sunset`` / ``Deprecation`` 标注
5. **可观测**：内置 ``X-API-Version-Requested`` / ``X-API-Version-Served`` 响应头

快速开始
--------

**1) 在 settings.py 注册版本**::

    from framework.versioning import VersionSpec, register_version, VersioningConfig

    register_version(VersionSpec(
        name="v1",
        status="deprecated",           # deprecated / sunset / active
        sunset_date="2026-12-31",
        successor="v2",
    ))
    register_version(VersionSpec(
        name="v2",
        status="active",
        is_default=True,
    ))
    register_version(VersionSpec(
        name="v3-beta",
        status="canary",
        canary_weight=10,              # 10% 流量
        canary_match=lambda req: req.headers.get("X-Beta-Tester") == "1",
    ))

    API_VERSIONING = VersioningConfig(
        default_version="v2",
        detection_order=("url", "header", "query"),
        allow_fallback=True,
    )

**2) 视图层使用**::

    from framework.versioning import versioned_view

    @versioned_view(min_version="v2", removed_in="v4")
    def my_view(request):
        ...

    # 或 ViewSet
    class OrderViewSet(viewsets.ViewSet):
        @versioned_view(min_version="v2", removed_in="v3")
        def list(self, request):
            ...

**3) 装饰器：方法级灰度**::

    from framework.versioning import only_for, since, until

    @only_for("v3-beta")
    def experimental_endpoint(request):
        # 仅 v3-beta 用户可访问，其他人返回 404
        ...
"""
from .core import (
    VersionSpec,
    VersionStatus,
    VersionRegistry,
    register_version,
    unregister_version,
    get_registry,
    resolve_version,
    set_active_version,
    get_active_version,
)
from .config import VersioningConfig, detect_version_from_request
from .decorators import (
    versioned_view,
    only_for,
    since,
    until,
)
from .middleware import VersioningMiddleware
from .drf import (
    VersionedMixin,
    get_versioned_api_view,
    get_versioned_viewset,
)

__all__ = [
    # 核心
    "VersionSpec",
    "VersionStatus",
    "VersionRegistry",
    "register_version",
    "unregister_version",
    "get_registry",
    "resolve_version",
    "set_active_version",
    "get_active_version",
    # 配置
    "VersioningConfig",
    "detect_version_from_request",
    # 装饰器
    "versioned_view",
    "only_for",
    "since",
    "until",
    # 中间件
    "VersioningMiddleware",
    # DRF 集成
    "VersionedMixin",
    "get_versioned_api_view",
    "get_versioned_viewset",
]
