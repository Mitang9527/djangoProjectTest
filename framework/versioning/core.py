# sync-init: skip
"""
版本管理 - 核心注册表与解析逻辑
==================================
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class VersionStatus(str, Enum):
    """版本生命周期状态"""
    CANARY = "canary"          # 灰度中，按权重/规则引流
    ACTIVE = "active"          # 正式可用
    DEPRECATED = "deprecated"  # 仍可用，但响应头标注 Sunset
    SUNSET = "sunset"          # 已下线 → 410 Gone
    DISABLED = "disabled"      # 手动禁用（紧急回滚）


@dataclass
class VersionSpec:
    """
    单个版本规格。

    Example::

        VersionSpec(
            name="v2",
            status=VersionStatus.ACTIVE,
            is_default=True,
            released_at=date(2026, 1, 1),
            successor="v3",
        )
    """
    name: str
    status: VersionStatus = VersionStatus.ACTIVE
    is_default: bool = False
    description: str = ""

    # 生命周期
    released_at: Optional[date] = None
    deprecated_at: Optional[date] = None
    sunset_date: Optional[date] = None
    successor: Optional[str] = None  # 推荐的迁移版本

    # 灰度策略（仅 canary 时生效）
    canary_weight: int = 0  # 0-100，整数百分比
    canary_match: Optional[Callable[[object], bool]] = None  # 自定义规则
    canary_header: str = "X-User-Tier"  # 灰度白名单 header
    canary_tier_value: str = "beta"  # 命中值

    # 兼容
    allow_fallback_to: Optional[str] = None  # 当该版本无对应方法时回退到哪个版本

    def is_available(self) -> bool:
        return self.status in (VersionStatus.ACTIVE, VersionStatus.CANARY, VersionStatus.DEPRECATED)

    def is_canary(self) -> bool:
        return self.status == VersionStatus.CANARY

    def is_deprecated(self) -> bool:
        return self.status in (VersionStatus.DEPRECATED, VersionStatus.SUNSET)


class VersionRegistry:
    """
    全局版本注册表（线程安全单例）。

    使用::

        registry = VersionRegistry()
        registry.register(VersionSpec(name="v1", status=VersionStatus.ACTIVE))
        registry.register(VersionSpec(name="v2", status=VersionStatus.ACTIVE, is_default=True))
    """
    _instance: Optional["VersionRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._versions: Dict[str, VersionSpec] = {}
        self._lock = threading.RLock()

    # --- CRUD ---

    def register(self, spec: VersionSpec) -> None:
        with self._lock:
            if spec.is_default:
                # 取消其它 default
                for v in self._versions.values():
                    v.is_default = False
            self._versions[spec.name] = spec
            logger.info(
                "[versioning] registered %s status=%s default=%s",
                spec.name, spec.status.value, spec.is_default,
            )

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._versions.pop(name, None) is not None

    def get(self, name: str) -> Optional[VersionSpec]:
        with self._lock:
            return self._versions.get(name)

    def all(self) -> List[VersionSpec]:
        with self._lock:
            return sorted(
                self._versions.values(),
                key=lambda v: (not v.is_default, v.name),
            )

    def default(self) -> Optional[VersionSpec]:
        with self._lock:
            for v in self._versions.values():
                if v.is_default:
                    return v
        return None

    def active(self) -> List[VersionSpec]:
        return [v for v in self.all() if v.is_available()]

    # --- 解析 ---

    def canary_should_route(self, spec: VersionSpec, request) -> bool:
        """灰度规则判定：返回 True 表示本请求应路由到该 canary 版本"""
        if not spec.is_canary():
            return spec.is_available()

        # 1) 自定义规则优先
        if spec.canary_match and spec.canary_match(request):
            return True

        # 2) Header 白名单
        tier = request.headers.get(spec.canary_header, "")
        if tier and tier == spec.canary_tier_value:
            return True

        # 3) 权重（基于 request id 哈希，保证同一用户稳定命中）
        if spec.canary_weight <= 0:
            return False
        if spec.canary_weight >= 100:
            return True
        # 用 thread-local 计数器实现简单负载均衡（生产可换 redis）
        bucket_key = self._bucket_key(request)
        h = abs(hash(bucket_key)) % 100
        return h < spec.canary_weight

    @staticmethod
    def _bucket_key(request) -> str:
        """灰度路由 key：登录用户用 user_id，否则用 IP+UA 哈希"""
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            return f"u:{user.pk}"
        # 匿名用户：IP+UA
        ip = request.META.get("REMOTE_ADDR", "0.0.0.0")  # nosec B104  # 此处 0.0.0.0 是取值默认值/字符串比较，不是 bind 绑定
        ua = request.META.get("HTTP_USER_AGENT", "")
        return f"a:{ip}:{hash(ua) % 10000}"

    def resolve_for_request(self, request) -> Optional[VersionSpec]:
        """
        根据请求判定要服务的版本。

        流程：
        1) 找所有 canary，按灰度规则选
        2) 否则用 default
        """
        # 灰度优先
        for spec in self.all():
            if spec.is_canary() and self.canary_should_route(spec, request):
                return spec
        # 默认
        return self.default()


# ============================================================================
# 顶层便捷函数
# ============================================================================

_global_registry: Optional[VersionRegistry] = None
_thread_local = threading.local()


def get_registry() -> VersionRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = VersionRegistry()
    return _global_registry


def register_version(spec: VersionSpec) -> None:
    """便捷注册函数"""
    get_registry().register(spec)


def unregister_version(name: str) -> bool:
    return get_registry().unregister(name)


def resolve_version(request=None) -> Optional[VersionSpec]:
    """
    解析当前请求应服务的版本。

    - 在请求处理过程中，本函数会从 request 上读 ``api_version``（由中间件/DRF 设置）
    - 若没有指定，则走灰度 → default 解析
    """
    if request is not None:
        requested = getattr(request, "api_version", None)
        if requested:
            spec = get_registry().get(requested)
            if spec and spec.is_available():
                return spec

    # 没有请求上下文时（如 CLI / 后台任务），返回 default
    return get_registry().default()


def set_active_version(version_name: str) -> None:
    """线程本地：覆盖当前线程的版本（用于后台任务 / 脚本强制指定）"""
    _thread_local.active_version = version_name


def get_active_version() -> Optional[str]:
    return getattr(_thread_local, "active_version", None)
