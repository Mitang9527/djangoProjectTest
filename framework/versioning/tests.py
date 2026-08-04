# sync-init: skip
"""
版本管理 - 单元测试
====================
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock

# 在导入前配置最小 Django settings（避免 DRF 类级访问 settings 失败）
import django
from django.conf import settings as _dj_settings
if not _dj_settings.configured:
    _dj_settings.configure(
        DEBUG=False,
        DATABASES={},
        INSTALLED_APPS=[],
        REST_FRAMEWORK={
            "DEFAULT_PAGINATION_CLASS": None,
            "PAGE_SIZE": 20,
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
        },
    )
    django.setup()

from .core import (
    VersionSpec,
    VersionStatus,
    VersionRegistry,
    get_registry,
    register_version,
    unregister_version,
    resolve_version,
)
from .config import VersioningConfig, detect_version_from_request
from .decorators import (
    versioned_view,
    only_for,
    since,
    until,
    _version_compare,
    _check_version_constraints,
)


def _reset_registry():
    """清空单例（测试间隔离）"""
    VersionRegistry._instance = None
    import framework.versioning.core as core
    core._global_registry = None


def _make_request(user_id=None, ip="1.2.3.4", ua="Mozilla", headers=None):
    """构造 fake request"""
    headers = headers or {}
    user = MagicMock()
    user.is_authenticated = bool(user_id)
    user.pk = user_id or 0
    req = MagicMock()
    req.META = {"REMOTE_ADDR": ip, "HTTP_USER_AGENT": ua}
    req.headers = headers
    req.user = user
    req.api_version = None
    return req


# ============================================================================
# VersionSpec 测试
# ============================================================================

class VersionSpecTest(unittest.TestCase):
    def test_default_status_active(self):
        v = VersionSpec(name="v1")
        assert v.status == VersionStatus.ACTIVE
        assert v.is_available()
        assert not v.is_deprecated()
        assert not v.is_canary()

    def test_canary_status(self):
        v = VersionSpec(name="v2", status=VersionStatus.CANARY)
        assert v.is_canary()
        assert v.is_available()  # canary 视为可用

    def test_sunset_not_available(self):
        v = VersionSpec(name="v1", status=VersionStatus.SUNSET)
        assert not v.is_available()
        assert v.is_deprecated()

    def test_disabled_not_available(self):
        v = VersionSpec(name="v1", status=VersionStatus.DISABLED)
        assert not v.is_available()
        assert not v.is_deprecated()  # disabled 不算 deprecated


# ============================================================================
# VersionRegistry 测试
# ============================================================================

class VersionRegistryTest(unittest.TestCase):
    def setUp(self):
        _reset_registry()

    def test_register_and_get(self):
        registry = get_registry()
        registry.register(VersionSpec(name="v1"))
        assert registry.get("v1").name == "v1"
        assert registry.get("v2") is None

    def test_register_default_clears_others(self):
        registry = get_registry()
        registry.register(VersionSpec(name="v1", is_default=True))
        registry.register(VersionSpec(name="v2", is_default=True))
        assert not registry.get("v1").is_default
        assert registry.get("v2").is_default
        assert registry.default().name == "v2"

    def test_unregister(self):
        registry = get_registry()
        registry.register(VersionSpec(name="v1"))
        assert registry.unregister("v1") is True
        assert registry.unregister("v1") is False  # 二次删

    def test_all_sorted_default_first(self):
        registry = get_registry()
        registry.register(VersionSpec(name="v1"))
        registry.register(VersionSpec(name="v2", is_default=True))
        registry.register(VersionSpec(name="v3"))
        all_ = registry.all()
        assert all_[0].name == "v2"  # default 在前
        assert [v.name for v in all_[1:]] == ["v1", "v3"]  # 其它按名字排序

    def test_default_returns_none_when_no_default(self):
        registry = get_registry()
        registry.register(VersionSpec(name="v1"))
        assert registry.default() is None

    def test_singleton(self):
        r1 = VersionRegistry()
        r2 = VersionRegistry()
        assert r1 is r2


# ============================================================================
# 灰度规则测试
# ============================================================================

class CanaryRuleTest(unittest.TestCase):
    def setUp(self):
        _reset_registry()

    def test_canary_weight_100_always_hit(self):
        registry = get_registry()
        v = VersionSpec(name="v3", status=VersionStatus.CANARY, canary_weight=100)
        for i in range(10):
            req = _make_request(user_id=f"u{i}")
            assert registry.canary_should_route(v, req) is True

    def test_canary_weight_0_never_hit(self):
        registry = get_registry()
        v = VersionSpec(name="v3", status=VersionStatus.CANARY, canary_weight=0)
        for i in range(10):
            req = _make_request(user_id=f"u{i}")
            assert registry.canary_should_route(v, req) is False

    def test_canary_custom_match(self):
        registry = get_registry()
        v = VersionSpec(
            name="v3", status=VersionStatus.CANARY,
            canary_match=lambda req: req.user.pk == "vip",
        )
        assert registry.canary_should_route(v, _make_request(user_id="vip")) is True
        assert registry.canary_should_route(v, _make_request(user_id="normal")) is False

    def test_canary_header_match(self):
        registry = get_registry()
        v = VersionSpec(name="v3", status=VersionStatus.CANARY, canary_weight=0)
        req = _make_request(headers={"X-User-Tier": "beta"})
        assert registry.canary_should_route(v, req) is True

    def test_canary_weight_distribution(self):
        registry = get_registry()
        v = VersionSpec(name="v3", status=VersionStatus.CANARY, canary_weight=50)
        hits = sum(
            1 for i in range(200)
            if registry.canary_should_route(v, _make_request(user_id=f"u{i}"))
        )
        # 期望 100±30
        assert 70 <= hits <= 130, f"灰度分布异常: {hits}/200"

    def test_non_canary_returns_availability(self):
        registry = get_registry()
        v = VersionSpec(name="v2", status=VersionStatus.ACTIVE)
        assert registry.canary_should_route(v, _make_request()) is True
        v_dep = VersionSpec(name="v1", status=VersionStatus.DEPRECATED)
        assert registry.canary_should_route(v_dep, _make_request()) is True
        v_sun = VersionSpec(name="v0", status=VersionStatus.SUNSET)
        assert registry.canary_should_route(v_sun, _make_request()) is False


# ============================================================================
# 版本号比较
# ============================================================================

class VersionCompareTest(unittest.TestCase):
    def test_basic_compare(self):
        assert _version_compare("v1", "v2") < 0
        assert _version_compare("v2", "v1") > 0
        assert _version_compare("v1", "v1") == 0

    def test_dot_compare(self):
        assert _version_compare("v2.1", "v2.2") < 0
        assert _version_compare("v2.10", "v2.9") > 0  # 数字比较，非字符串

    def test_beta_suffix_ignored(self):
        # v3-beta 与 v3 视为相等（简化的版本比较）
        assert _version_compare("v3-beta", "v3") == 0

    def test_two_digits(self):
        assert _version_compare("v10", "v2") > 0


# ============================================================================
# 装饰器
# ============================================================================

class DecoratorTest(unittest.TestCase):
    def test_since_passes(self):
        @since("v2")
        def view(request): return "ok"
        req = MagicMock(api_version="v2")
        assert view(req) == "ok"

    def test_since_blocks_lower(self):
        @since("v2")
        def view(request): return "ok"
        req = MagicMock(api_version="v1")
        resp = view(req)
        assert resp.status_code == 404

    def test_until_blocks_higher(self):
        @until("v3")
        def view(request): return "ok"
        req = MagicMock(api_version="v4")
        resp = view(req)
        assert resp.status_code == 404

    def test_only_for_passes(self):
        @only_for("v3-beta")
        def view(request): return "ok"
        req = MagicMock(api_version="v3-beta")
        assert view(req) == "ok"

    def test_only_for_blocks_others(self):
        @only_for("v3-beta")
        def view(request): return "ok"
        req = MagicMock(api_version="v2")
        resp = view(req)
        assert resp.status_code == 404

    def test_removed_in_returns_410(self):
        _reset_registry()
        v4 = VersionSpec(name="v4", status=VersionStatus.ACTIVE, is_default=True)
        register_version(v4)
        @versioned_view(removed_in="v4")
        def view(request): return "ok"
        req = MagicMock(api_version="v4")
        resp = view(req)
        assert resp.status_code == 410

    def test_no_version_passes(self):
        @since("v2")
        def view(request): return "ok"
        req = MagicMock(api_version=None)
        # 未指定版本时放行
        assert view(req) == "ok"

    def test_metadata_preserved(self):
        @since("v2")
        def view(request): return "ok"
        assert hasattr(view, "__versioned__")
        assert view.__versioned__["min_version"] == "v2"


# ============================================================================
# 探测
# ============================================================================

class DetectVersionTest(unittest.TestCase):
    def test_url_detection(self):
        req = MagicMock()
        req.path_info = "/api/v2/users"
        req.headers = {}
        req.GET = {}
        v = detect_version_from_request(req, VersioningConfig())
        assert v == "v2"

    def test_header_detection(self):
        req = MagicMock()
        req.path_info = "/api/users"
        req.headers = {"X-API-Version": "v3"}
        req.GET = {}
        v = detect_version_from_request(req, VersioningConfig())
        assert v == "v3"

    def test_query_detection(self):
        req = MagicMock()
        req.path_info = "/api/users"
        req.headers = {}
        req.GET = {"version": "v1"}
        v = detect_version_from_request(req, VersioningConfig())
        assert v == "v1"

    def test_url_priority_over_header(self):
        req = MagicMock()
        req.path_info = "/api/v2/users"
        req.headers = {"X-API-Version": "v3"}
        req.GET = {"version": "v1"}
        v = detect_version_from_request(req, VersioningConfig())
        assert v == "v2"

    def test_not_detected(self):
        req = MagicMock()
        req.path_info = "/api/users"
        req.headers = {}
        req.GET = {}
        v = detect_version_from_request(req, VersioningConfig())
        assert v is None

    def test_custom_url_pattern(self):
        cfg = VersioningConfig(url_pattern=r"^/v(?P<version>\d+)/api/")
        req = MagicMock()
        req.path_info = "/v3/api/users"
        req.headers = {}
        req.GET = {}
        v = detect_version_from_request(req, cfg)
        assert v == "3"


# ============================================================================
# 顶层函数
# ============================================================================

class TopLevelApiTest(unittest.TestCase):
    def setUp(self):
        _reset_registry()

    def test_resolve_version_default(self):
        register_version(VersionSpec(name="v2", is_default=True))
        spec = resolve_version()
        assert spec.name == "v2"

    def test_resolve_version_with_request(self):
        register_version(VersionSpec(name="v2", is_default=True))
        register_version(VersionSpec(name="v3", status=VersionStatus.CANARY, canary_weight=0))
        req = _make_request()
        req.api_version = "v3"
        spec = resolve_version(req)
        assert spec.name == "v3"

    def test_resolve_version_unavailable_falls_back(self):
        register_version(VersionSpec(name="v2", is_default=True))
        req = _make_request()
        req.api_version = "v1-old"  # 未注册
        spec = resolve_version(req)
        assert spec.name == "v2"

    def test_set_active_version(self):
        from .core import set_active_version, get_active_version
        set_active_version("v3")
        assert get_active_version() == "v3"


if __name__ == "__main__":
    unittest.main(verbosity=2)
