# sync-init: skip
"""
版本管理 - 配置与版本探测
==========================
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

from django.conf import settings

from .core import VersionSpec, VersionStatus, get_registry

logger = logging.getLogger(__name__)


@dataclass
class VersioningConfig:
    """
    项目级版本管理配置。

    在 settings.py 中::

        from framework.versioning import VersioningConfig, register_version, VersionSpec

        API_VERSIONING = VersioningConfig(
            default_version="v2",
            detection_order=("url", "header", "query"),
            allow_fallback=True,
        )

        register_version(VersionSpec(name="v1", status=VersionStatus.DEPRECATED, successor="v2"))
        register_version(VersionSpec(name="v2", status=VersionStatus.ACTIVE, is_default=True))
    """
    default_version: str = "v1"
    detection_order: Tuple[str, ...] = ("url", "header", "query")
    allow_fallback: bool = True
    url_pattern: str = r"^/api/(?P<version>v\d+(?:\.\d+)?(?:-[a-z0-9]+)?)/"
    header_name: str = "X-API-Version"
    query_param: str = "version"
    inactive_status_codes: bool = True  # 410 Gone for sunset, 404 for disabled

    def get_from_settings(self) -> "VersioningConfig":
        """从 settings.API_VERSIONING 加载（如果存在）"""
        return getattr(settings, "API_VERSIONING", self)


def detect_version_from_request(request, config: Optional[VersioningConfig] = None) -> Optional[str]:
    """
    按 detection_order 顺序从 request 中探测版本字符串。

    Returns: ``"v1"`` / ``"v2.1"`` / ``"v3-beta"`` 等，None 表示未指定
    """
    cfg = config or VersioningConfig().get_from_settings()
    path = request.path_info
    for method in cfg.detection_order:
        if method == "url":
            m = re.match(cfg.url_pattern, path)
            if m:
                return m.group("version")
        elif method == "header":
            v = request.headers.get(cfg.header_name)
            if v:
                return v.strip()
        elif method == "query":
            v = request.GET.get(cfg.query_param)
            if v:
                return v.strip()
    return None


def init_from_settings() -> None:
    """
    在 Django AppConfig.ready() 中调用，从 settings 自动注册版本。

    Example::

        class SaasConfig(AppConfig):
            def ready(self):
                from framework.versioning.config import init_from_settings
                init_from_settings()
    """
    cfg = VersioningConfig().get_from_settings()
    if not cfg:
        return
    registry = get_registry()
    # 若 registry 为空，注册一个 default
    if not registry.all():
        registry.register(VersionSpec(
            name=cfg.default_version,
            status=VersionStatus.ACTIVE,
            is_default=True,
        ))
        logger.info("[versioning] auto-registered default %s", cfg.default_version)
