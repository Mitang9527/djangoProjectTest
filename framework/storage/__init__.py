"""
framework.storage —— 统一对象存储抽象层
======================================

屏蔽底层差异（本地磁盘 / 阿里云 OSS / S3·MinIO），提供一致的上传/下载/删除/URL 接口。

快速上手::

    from framework.storage import get_storage, upload, get_url

    storage = get_storage()                     # 按 settings.OSS_CONFIG 选择后端
    url = storage.upload("avatars/u1.png", data, public=True)
    url = get_url("avatars/u1.png", public=True)

便捷函数（推荐在视图/任务中直接用，内部复用单例后端）::

    upload("key", data, public=True)            -> 访问 URL
    download("key")                             -> bytes
    delete("key")
    get_url("key", public=False, expires=600)   -> 签名临时 URL
    exists("key") / list("prefix/") / stat("key")

切换后端：在 settings 中配置 ``OSS_CONFIG``（来自 global_config.oss）与
``STORAGE_BACKEND``。local 始终可用；云后端不可用时默认降级 local（strict=True 则快速失败）。
"""

from .base import StorageBackend
from .exceptions import (
    StorageError,
    StorageConfigError,
    StorageConnectionError,
    StorageNotFoundError,
    StorageAlreadyExistsError,
    StorageUploadError,
    StorageDownloadError,
    StorageBackendUnavailable,
)
from .factory import get_storage, clear_cache
from .local import LocalStorageBackend
from .oss import AliyunOSSBackend
from .s3 import S3CompatibleBackend
from .django_storage import DjangoOSSStorage

__all__ = [
    "StorageBackend",
    "StorageError",
    "StorageConfigError",
    "StorageConnectionError",
    "StorageNotFoundError",
    "StorageAlreadyExistsError",
    "StorageUploadError",
    "StorageDownloadError",
    "StorageBackendUnavailable",
    "get_storage",
    "clear_cache",
    "LocalStorageBackend",
    "AliyunOSSBackend",
    "S3CompatibleBackend",
    "DjangoOSSStorage",
    # 便捷函数
    "upload",
    "upload_file",
    "download",
    "download_file",
    "delete",
    "exists",
    "get_url",
    "list_objects",
    "stat",
]


# --------------------------------------------------------------------------- #
# 模块级便捷函数：直接操作默认后端，业务代码无需手动 get_storage()
# --------------------------------------------------------------------------- #
def _default_backend() -> StorageBackend:
    return get_storage()


def upload(key: str, data, *, public: bool = False, content_type: str = None,
           metadata: dict = None) -> str:
    """上传内容并返回访问 URL。"""
    return _default_backend().upload(key, data, public=public,
                                     content_type=content_type, metadata=metadata)


def upload_file(key: str, file_path: str, *, public: bool = False,
                content_type: str = None, metadata: dict = None) -> str:
    return _default_backend().upload_file(key, file_path, public=public,
                                          content_type=content_type, metadata=metadata)


def download(key: str) -> bytes:
    return _default_backend().download(key)


def download_file(key: str, dest_path: str) -> int:
    return _default_backend().download_file(key, dest_path)


def delete(key: str) -> None:
    _default_backend().delete(key)


def exists(key: str) -> bool:
    return _default_backend().exists(key)


def get_url(key: str, *, public: bool = False, expires: int = None) -> str:
    return _default_backend().get_url(key, public=public, expires=expires)


def list_objects(prefix: str = "", *, max_keys: int = 1000) -> list:
    return _default_backend().list(prefix, max_keys=max_keys)


def stat(key: str) -> dict:
    return _default_backend().stat(key)
