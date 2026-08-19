"""
存储后端工厂
============

根据 Django settings 中的 :data:`OSS_CONFIG` / :data:`STORAGE_BACKEND` 构建对应的
存储后端实例。业务代码只需 ``from framework.storage import get_storage`` 即可，
无需关心底层是 local / aliyun / s3。

配置来源（推荐在 ``settings/base.py`` 中注入 ``OSS_CONFIG``，见下方说明）：
    OSS_CONFIG = global_config.oss.model_dump()
    STORAGE_BACKEND = OSS_CONFIG.get("backend", "local")

降级策略（遵守项目「基础设施须尊重 enabled + 快速失败」约定）：
- ``backend=local`` 始终可用，作为默认与兜底。
- 若配置了云后端但 SDK 缺失 / 服务不可达：
  - ``strict=True``：抛 :class:`StorageBackendUnavailable`（快速失败，便于告警）。
  - ``strict=False``（默认）：自动降级为 local 后端并打 warning，保证业务不中断。
"""

from __future__ import annotations

import os
from typing import Optional

from django.conf import settings

from loguru import logger

from .base import StorageBackend
from .exceptions import StorageBackendUnavailable, StorageConfigError

# 模块级缓存：同一进程内重复调用 get_storage 不重建连接
_cache: dict = {}


def _resolve_config() -> dict:
    """优先读 Django settings.OSS_CONFIG，回退到环境变量。"""
    cfg = getattr(settings, "OSS_CONFIG", None)
    if isinstance(cfg, dict):
        return cfg
    # 环境变量直读（未接入 settings 时也能用）
    return {
        "enabled": os.environ.get("OSS_ENABLED", "False").lower() in ("1", "true", "yes", "on"),
        "backend": os.environ.get("OSS_BACKEND", "local"),
        "bucket": os.environ.get("OSS_BUCKET", ""),
        "endpoint": os.environ.get("OSS_ENDPOINT", ""),
        "region": os.environ.get("OSS_REGION", ""),
        "access_key": os.environ.get("OSS_ACCESS_KEY", ""),
        "secret_key": os.environ.get("OSS_SECRET_KEY", ""),
        "use_ssl": os.environ.get("OSS_USE_SSL", "True").lower() in ("1", "true", "yes", "on"),
        "custom_domain": os.environ.get("OSS_CUSTOM_DOMAIN", ""),
        "url_expire": int(os.environ.get("OSS_URL_EXPIRE", "3600")),
        "local_root": os.environ.get("OSS_LOCAL_ROOT", "media/oss"),
        "public_base_url": os.environ.get("OSS_PUBLIC_BASE_URL", ""),
    }


def _build_local(cfg: dict) -> StorageBackend:
    from .local import LocalStorageBackend

    root = cfg.get("local_root") or "media/oss"
    # 只在未给绝对路径时回退到 settings.BASE_DIR（避免跨盘 relpath 报错）
    if not os.path.isabs(root):
        base = getattr(settings, "BASE_DIR", os.getcwd())
        root = os.path.join(str(base), root)
    media_url = getattr(settings, "MEDIA_URL", "media/").strip("/")
    # 推导本地 OSS 根的对外 URL 前缀；跨盘（测试用独立临时目录）时用兜底
    try:
        rel = os.path.relpath(root, str(getattr(settings, "BASE_DIR", os.getcwd()))).replace(os.sep, "/")
        local_media_url = f"{media_url}/{os.path.basename(rel)}/" if media_url else f"{os.path.basename(rel)}/"
    except ValueError:
        local_media_url = f"{media_url}/oss/" if media_url else "oss/"
    return LocalStorageBackend(root, media_url=local_media_url,
                              public_base_url=cfg.get("public_base_url", ""))


def _build(cfg: dict, *, strict: bool) -> StorageBackend:
    backend = (cfg.get("backend") or "local").lower()

    if backend in ("local", "filesystem", "disk"):
        return _build_local(cfg)

    if backend in ("aliyun", "oss", "aliyun_oss"):
        from .oss import AliyunOSSBackend
        try:
            return AliyunOSSBackend(
                bucket=cfg.get("bucket", ""),
                endpoint=cfg.get("endpoint", ""),
                access_key=cfg.get("access_key", ""),
                secret_key=cfg.get("secret_key", ""),
                region=cfg.get("region", ""),
                custom_domain=cfg.get("custom_domain", ""),
                url_expire=cfg.get("url_expire", 3600),
            )
        except StorageBackendUnavailable as exc:
            if strict:
                raise
            logger.warning(f"[storage] 阿里云 OSS 不可用，降级 local: {exc}")
            return _build_local(cfg)

    if backend in ("s3", "minio", "aws", "cos", "obs"):
        from .s3 import S3CompatibleBackend
        try:
            return S3CompatibleBackend(
                bucket=cfg.get("bucket", ""),
                endpoint=cfg.get("endpoint", ""),
                access_key=cfg.get("access_key", ""),
                secret_key=cfg.get("secret_key", ""),
                region=cfg.get("region", ""),
                use_ssl=cfg.get("use_ssl", True),
                custom_domain=cfg.get("custom_domain", ""),
                url_expire=cfg.get("url_expire", 3600),
            )
        except StorageBackendUnavailable as exc:
            if strict:
                raise
            logger.warning(f"[storage] S3 后端不可用，降级 local: {exc}")
            return _build_local(cfg)

    raise StorageConfigError(f"不支持的存储 backend: {backend!r}")


def get_storage(alias: Optional[str] = None, *, strict: bool = False,
                force_reload: bool = False) -> StorageBackend:
    """获取存储后端实例。

    :param alias: 预留多实例扩展（当前单例，忽略）。
    :param strict: True 时云后端不可用则抛异常；False 自动降级 local。
    :param force_reload: 绕过缓存重建。
    """
    cache_key = f"{alias or 'default'}:{strict}"
    if not force_reload and cache_key in _cache:
        return _cache[cache_key]
    cfg = _resolve_config()
    backend = _build(cfg, strict=strict)
    _cache[cache_key] = backend
    logger.info(f"[storage] 已初始化存储后端: {backend.backend_type}")
    return backend


def clear_cache() -> None:
    """测试或配置热更新时清空后端缓存。"""
    _cache.clear()
