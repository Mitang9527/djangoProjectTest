# sync-init: skip
"""
版本管理 - 使用示例
====================
"""
from __future__ import annotations

import sys
import os
from datetime import date

# 允许独立运行
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# 配置最小 Django
import django
from django.conf import settings as _dj_settings
if not _dj_settings.configured:
    _dj_settings.configure(
        DEBUG=False,
        DATABASES={},
        INSTALLED_APPS=[],
        REST_FRAMEWORK={
            "PAGE_SIZE": 20,
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
        },
    )
    django.setup()

from utils.versioning.core import (
    VersionSpec,
    VersionStatus,
    VersionRegistry,
    get_registry,
    register_version,
    unregister_version,
    resolve_version,
)
from utils.versioning.config import VersioningConfig, detect_version_from_request
from utils.versioning.decorators import versioned_view, only_for, since, until, _version_compare


def _reset_registry():
    """清空单例（仅供 examples 使用）"""
    VersionRegistry._instance = None
    import utils.versioning.core as core
    core._global_registry = None


def example_1_basic_register():
    """例 1: 基本注册与查询"""
    print("\n=== Example 1: 基本注册 ===")
    _reset_registry()

    register_version(VersionSpec(name="v1", status=VersionStatus.ACTIVE))
    register_version(VersionSpec(name="v2", status=VersionStatus.ACTIVE, is_default=True))
    register_version(VersionSpec(name="v3-beta", status=VersionStatus.CANARY, canary_weight=20))

    registry = get_registry()
    print(f"已注册: {[v.name for v in registry.all()]}")
    assert len(registry.all()) == 3
    assert registry.default().name == "v2"
    print("OK")


def example_2_lifecycle():
    """例 2: 生命周期转换"""
    print("\n=== Example 2: 生命周期 ===")
    _reset_registry()

    v1 = VersionSpec(name="v1", status=VersionStatus.DEPRECATED,
                     deprecated_at=date(2026, 1, 1), sunset_date=date(2026, 12, 31),
                     successor="v2")
    v2 = VersionSpec(name="v2", status=VersionStatus.ACTIVE, is_default=True)
    register_version(v1)
    register_version(v2)

    assert v1.is_deprecated()
    assert v1.is_available()
    assert v2.is_available()
    assert v2.successor is None
    assert v1.successor == "v2"
    print(f"v1 status={v1.status.value} 可用={v1.is_available()}")
    print(f"v2 status={v2.status.value} 可用={v2.is_available()}")
    print("OK")


def example_3_canary():
    """例 3: 灰度规则"""
    print("\n=== Example 3: 灰度规则 ===")
    _reset_registry()

    v3 = VersionSpec(
        name="v3",
        status=VersionStatus.CANARY,
        canary_weight=50,  # 50% 流量
    )
    register_version(VersionSpec(name="v2", status=VersionStatus.ACTIVE, is_default=True))
    register_version(v3)
    registry = get_registry()

    class FakeRequest:
        def __init__(self, user_id=None, ip="1.2.3.4", ua="Mozilla"):
            self.META = {"REMOTE_ADDR": ip, "HTTP_USER_AGENT": ua}
            self.headers = {}
            self.user = type("U", (), {"is_authenticated": bool(user_id), "pk": user_id})()

    # 模拟 100 个不同用户
    hit = 0
    for i in range(100):
        req = FakeRequest(user_id=f"u{i}")
        if registry.canary_should_route(v3, req):
            hit += 1
    print(f"100 个用户命中 v3 灰度的数量: {hit}/100 (预期 ~50)")
    assert 30 <= hit <= 70, f"灰度命中比例异常: {hit}"
    print("OK")


def example_4_version_compare():
    """例 4: 版本号比较"""
    print("\n=== Example 4: 版本号比较 ===")
    assert _version_compare("v1", "v2") < 0
    assert _version_compare("v2.1", "v2") > 0
    assert _version_compare("v2.1", "v2.10") < 0
    assert _version_compare("v3-beta", "v3") == 0  # 拆 beta 后都是 v3
    assert _version_compare("v10", "v9") > 0
    print("v1<v2 OK, v2.1>v2 OK, v2.1<v2.10 OK, v3-beta==v3 OK, v10>v9 OK")
    print("OK")


def example_5_decorators():
    """例 5: 装饰器"""
    print("\n=== Example 5: 装饰器 ===")

    @since("v2")
    def view_a(request):
        return "A"

    @until("v3")
    def view_b(request):
        return "B"

    @only_for("v3-beta")
    def view_c(request):
        return "C"

    @versioned_view(min_version="v2", removed_in="v4")
    def view_d(request):
        return "D"

    # 模拟 request.api_version
    class FakeReq:
        def __init__(self, v): self.api_version = v

    # view_a: v1 应该 404, v2 通过
    assert view_a(FakeReq("v1")).status_code == 404
    assert view_a(FakeReq("v2")) == "A"
    assert view_a(FakeReq("v3")) == "A"
    print("since('v2'): v1 拒绝, v2/v3 通过 ✓")

    # view_b: v2 通过, v4 拒绝
    assert view_b(FakeReq("v2")) == "B"
    assert view_b(FakeReq("v3")) == "B"
    assert view_b(FakeReq("v4")).status_code == 404
    print("until('v3'): v2/v3 通过, v4 拒绝 ✓")

    # view_c: 仅 v3-beta
    assert view_c(FakeReq("v3-beta")) == "C"
    assert view_c(FakeReq("v2")).status_code == 404
    print("only_for('v3-beta'): 仅指定版本通过 ✓")

    # view_d: v1 拒绝, v4 -> 410 Gone
    assert view_d(FakeReq("v1")).status_code == 404
    assert view_d(FakeReq("v3")) == "D"
    resp = view_d(FakeReq("v4"))
    assert resp.status_code == 410
    print("removed_in='v4': v1 拒绝, v3 通过, v4 → 410 ✓")
    print("OK")


def example_6_detect_version():
    """例 6: 从 request 探测版本"""
    print("\n=== Example 6: 探测版本 ===")

    class FakeReq:
        def __init__(self, path="", headers=None, query=None):
            self.path_info = path
            self.headers = headers or {}
            self.GET = query or {}

    cfg = VersioningConfig()

    # URL 形式
    v = detect_version_from_request(FakeReq(path="/api/v2/users"), cfg)
    assert v == "v2", v
    print(f"URL 形式 /api/v2/users -> {v} ✓")

    # Header 形式
    v = detect_version_from_request(
        FakeReq(path="/api/users", headers={"X-API-Version": "v3"}), cfg
    )
    assert v == "v3", v
    print(f"Header X-API-Version: v3 -> {v} ✓")

    # Query 形式
    v = detect_version_from_request(
        FakeReq(path="/api/users", query={"version": "v1"}), cfg
    )
    assert v == "v1", v
    print(f"Query ?version=v1 -> {v} ✓")

    # 未指定
    v = detect_version_from_request(FakeReq(path="/api/users"), cfg)
    assert v is None
    print(f"未指定 -> None ✓")
    print("OK")


def main():
    print("=" * 60)
    print("版本管理示例 - 运行中")
    print("=" * 60)
    example_1_basic_register()
    example_2_lifecycle()
    example_3_canary()
    example_4_version_compare()
    example_5_decorators()
    example_6_detect_version()
    print("\n" + "=" * 60)
    print("全部示例通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
