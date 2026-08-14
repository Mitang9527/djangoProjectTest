"""
S3 兼容存储后端（AWS S3 / MinIO / 腾讯云 COS / 华为 OBS 等）
=============================================================

依赖 ``boto3``（可选，未安装时仅在使用时抛 :class:`StorageBackendUnavailable`）。
通过配置 ``endpoint_url`` 即可对接 MinIO 等自建兼容服务。

配置来源（由 factory 统一注入）：
    OSS_BUCKET / OSS_ENDPOINT(=endpoint_url) / OSS_REGION
    OSS_ACCESS_KEY / OSS_SECRET_KEY / OSS_USE_SSL
"""

from __future__ import annotations

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


class S3CompatibleBackend(StorageBackend):
    backend_type = "s3"

    def __init__(self, bucket: str, endpoint: str, access_key: str, secret_key: str,
                 *, region: str = "", use_ssl: bool = True,
                 custom_domain: str = "", url_expire: int = 3600):
        if not bucket:
            raise StorageConfigError("S3 后端需要 bucket")
        self.bucket_name = bucket
        self.region = region or "us-east-1"
        self.custom_domain = custom_domain.rstrip("/")
        self.url_expire = url_expire

        try:
            import boto3  # lazy import
            from botocore.config import Config
        except ImportError as exc:
            raise StorageBackendUnavailable(
                "未安装 boto3，无法使用 S3 后端（pip install boto3）"
            ) from exc
        self._boto3 = boto3

        scheme = "https" if use_ssl else "http"
        endpoint_url = None
        if endpoint:
            endpoint_url = endpoint if "://" in endpoint else f"{scheme}://{endpoint}"

        try:
            client_cfg = Config(signature_version="s3v4", retries={"max_attempts": 3})
            self._client = boto3.client(
                "s3",
                aws_access_key_id=access_key or None,
                aws_secret_access_key=secret_key or None,
                region_name=self.region,
                endpoint_url=endpoint_url,
                config=client_cfg,
            )
            # 探活
            self._client.head_bucket(Bucket=bucket)
        except Exception as exc:
            raise StorageConnectionError(f"S3 连接失败: {exc}") from exc

    def _object(self, key: str) -> str:
        return self._normalize_key(key)

    def _upload_bytes(self, key, data, *, content_type=None, public=False, metadata=None):
        key = self._object(key)
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
        try:
            self._client.put_object(Bucket=self.bucket_name, Key=key, Body=data, **(extra or {}))
        except Exception as exc:
            raise StorageUploadError(f"S3 上传失败 {key}: {exc}") from exc
        logger.debug(f"[storage:s3] 上传 {key} ({len(data)}B)")
        return self._get_url(key, public=public)

    def _download_bytes(self, key):
        key = self._object(key)
        try:
            resp = self._client.get_object(Bucket=self.bucket_name, Key=key)
            return resp["Body"].read()
        except self._client.exceptions.NoSuchKey:
            raise StorageNotFoundError(f"对象不存在: {key}")
        except Exception as exc:
            raise StorageConnectionError(f"S3 下载失败 {key}: {exc}") from exc

    def _delete(self, key):
        key = self._object(key)
        try:
            self._client.delete_object(Bucket=self.bucket_name, Key=key)
        except Exception as exc:
            logger.warning(f"[storage:s3] 删除失败 {key}: {exc}")

    def _exists(self, key):
        try:
            self._client.head_object(Bucket=self.bucket_name, Key=self._object(key))
            return True
        except Exception:
            return False

    def _get_url(self, key, *, expires=None, public=False):
        key = self._object(key)
        if public and self.custom_domain:
            return f"{self.custom_domain}/{key}"
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expires or self.url_expire,
            )
        except Exception as exc:
            raise StorageConnectionError(f"S3 生成签名 URL 失败 {key}: {exc}") from exc

    def _list(self, prefix="", *, max_keys=1000):
        prefix = self._object(prefix)
        keys: List[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
                    if len(keys) >= max_keys:
                        return keys
        except Exception as exc:
            raise StorageConnectionError(f"S3 列举失败: {exc}") from exc
        return keys

    def _stat(self, key):
        key = self._object(key)
        try:
            head = self._client.head_object(Bucket=self.bucket_name, Key=key)
            return {
                "size": head["ContentLength"],
                "last_modified": head.get("LastModified"),
                "etag": head.get("ETag"),
            }
        except Exception as exc:
            raise StorageNotFoundError(f"对象不存在或取元数据失败 {key}: {exc}") from exc
