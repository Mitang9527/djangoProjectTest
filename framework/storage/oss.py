"""
阿里云 OSS 存储后端
====================

依赖 ``oss2``（可选，未安装时 import 此模块不会失败，仅在使用时抛
:class:`StorageBackendUnavailable`）。与项目「extensions 可选可删」理念一致。

环境变量 / 配置来源（由 factory 统一注入）：
    OSS_BUCKET / OSS_ENDPOINT / OSS_ACCESS_KEY / OSS_SECRET_KEY
可选：
    OSS_CUSTOM_DOMAIN（绑定的自定义域名/CDN，用于公开 URL）
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from loguru import logger

from .base import StorageBackend
from .exceptions import (
    StorageBackendUnavailable,
    StorageConfigError,
    StorageConnectionError,
    StorageNotFoundError,
    StorageUploadError,
)


class AliyunOSSBackend(StorageBackend):
    backend_type = "aliyun"

    def __init__(self, bucket: str, endpoint: str, access_key: str, secret_key: str,
                 *, region: str = "", custom_domain: str = "", url_expire: int = 3600):
        if not bucket or not endpoint:
            raise StorageConfigError("阿里云 OSS 需要 bucket 与 endpoint")
        self.bucket_name = bucket
        self.endpoint = endpoint
        self.custom_domain = custom_domain.rstrip("/")
        self.url_expire = url_expire

        try:
            import oss2  # lazy import
        except ImportError as exc:
            raise StorageBackendUnavailable(
                "未安装 oss2，无法使用阿里云 OSS 后端（pip install oss2）"
            ) from exc

        self._oss2 = oss2
        try:
            auth = oss2.Auth(access_key, secret_key)
            self._bucket = oss2.Bucket(auth, endpoint, bucket, connect_timeout=10)
            # 轻量探活：不列举，只取 bucket 存在性（list_objects 前先 try head）
            self._bucket.get_bucket_info()
        except Exception as exc:  # 网络/鉴权失败
            raise StorageConnectionError(f"阿里云 OSS 连接失败: {exc}") from exc

    def _object(self, key: str) -> str:
        return self._normalize_key(key)

    def _upload_bytes(self, key, data, *, content_type=None, public=False, metadata=None):
        key = self._object(key)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if metadata:
            for k, v in metadata.items():
                headers[f"x-oss-meta-{k}"] = str(v)
        try:
            self._bucket.put_object(key, data, headers=headers or None)
        except Exception as exc:
            raise StorageUploadError(f"OSS 上传失败 {key}: {exc}") from exc
        logger.debug(f"[storage:oss] 上传 {key} ({len(data)}B)")
        return self._get_url(key, public=public)

    def _download_bytes(self, key):
        key = self._object(key)
        try:
            resp = self._bucket.get_object(key)
            return resp.read()
        except self._oss2.exceptions.NoSuchKey:
            raise StorageNotFoundError(f"对象不存在: {key}")
        except Exception as exc:
            raise StorageConnectionError(f"OSS 下载失败 {key}: {exc}") from exc

    def _delete(self, key):
        key = self._object(key)
        try:
            self._bucket.delete_object(key)
        except Exception as exc:  # 即便出错也尽量幂等
            logger.warning(f"[storage:oss] 删除失败 {key}: {exc}")

    def _exists(self, key):
        return self._bucket.object_exists(self._object(key))

    def _get_url(self, key, *, expires=None, public=False):
        key = self._object(key)
        if public and self.custom_domain:
            return f"{self.custom_domain}/{key}"
        if public:
            # OSS 公开读 bucket 默认可通过 endpoint 直链访问
            return f"{self.endpoint.rstrip('/')}/{self.bucket_name}/{key}"
        try:
            return self._bucket.sign_url("GET", key, expires or self.url_expire)
        except Exception as exc:
            raise StorageConnectionError(f"OSS 生成签名 URL 失败 {key}: {exc}") from exc

    def _list(self, prefix="", *, max_keys=1000):
        prefix = self._object(prefix)
        keys: List[str] = []
        try:
            for obj in self._oss2.ObjectIterator(self._bucket, prefix=prefix, max_keys=max_keys):
                keys.append(obj.key)
        except Exception as exc:
            raise StorageConnectionError(f"OSS 列举失败: {exc}") from exc
        return keys

    def _stat(self, key):
        key = self._object(key)
        try:
            meta = self._bucket.get_object_meta(key)
            return {
                "size": int(meta.headers.get("Content-Length", 0)),
                "last_modified": meta.headers.get("Last-Modified"),
                "etag": meta.headers.get("ETag"),
            }
        except self._oss2.exceptions.NoSuchKey:
            raise StorageNotFoundError(f"对象不存在: {key}")
        except Exception as exc:
            raise StorageConnectionError(f"OSS 取元数据失败 {key}: {exc}") from exc
