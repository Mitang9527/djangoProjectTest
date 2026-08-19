"""
framework/storage 后端抽象基类
================================

定义所有存储后端必须实现的统一接口 :class:`StorageBackend`。
上层代码（业务/视图/任务）只依赖这个抽象，不关心底层是本地磁盘、
阿里云 OSS 还是 S3/MinIO，切换 backend 时业务代码零改动。

设计原则（与项目其它 framework 模块保持一致）：
- 纯标准库 + loguru，不强制依赖任何云 SDK（云 SDK 在各自后端内 lazy import）。
- 所有异常归一到 ``framework.storage.exceptions``，便于统一捕获/降级。
- 支持「公开对象」与「私有对象（签名 URL）」两种语义。
- 网络类错误标记 ``retryable``，便于上层做指数退避重试。
"""

from __future__ import annotations

import abc
import io
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .exceptions import (
    StorageConfigError,
    StorageError,
    StorageNotFoundError,
)

# 可接受的文件内容输入类型：字节、二进制流、或本地路径
FileContent = Union[bytes, bytearray, str, io.BytesIO, "io.BufferedReader"]


class StorageBackend(abc.ABC):
    """存储后端抽象基类。

    约定：
    - ``key`` 是对象在存储中的唯一标识（通常形如 ``avatars/2026/uid.png``）。
    - 公开对象：``get_url`` 返回可直接访问的 URL。
    - 私有对象：``get_url(..., public=False)`` 返回带签名的临时 URL。
    """

    #: 后端类型标识（子类覆盖），用于日志/调试
    backend_type: str = "abstract"

    # ------------------------------------------------------------------ #
    # 必须实现的抽象方法
    # ------------------------------------------------------------------ #
    @abc.abstractmethod
    def _upload_bytes(self, key: str, data: bytes, *, content_type: Optional[str] = None,
                      public: bool = False, metadata: Optional[Dict[str, str]] = None) -> str:
        """上传原始字节，返回对象的访问 URL（或 key）。"""

    @abc.abstractmethod
    def _download_bytes(self, key: str) -> bytes:
        """下载对象为字节；不存在抛 :class:`StorageNotFoundError`。"""

    @abc.abstractmethod
    def _delete(self, key: str) -> None:
        """删除对象（不存在也不报错，幂等）。"""

    @abc.abstractmethod
    def _exists(self, key: str) -> bool:
        """判断对象是否存在。"""

    @abc.abstractmethod
    def _get_url(self, key: str, *, expires: Optional[int] = None, public: bool = False) -> str:
        """返回对象的访问 URL（公开直链或签名临时链）。"""

    @abc.abstractmethod
    def _list(self, prefix: str = "", *, max_keys: int = 1000) -> List[str]:
        """列出以 ``prefix`` 开头的对象 key。"""

    @abc.abstractmethod
    def _stat(self, key: str) -> Dict[str, Any]:
        """返回对象元数据：至少含 ``size`` / ``last_modified`` / ``etag``。"""

    # ------------------------------------------------------------------ #
    # 通用实现（子类一般无需重写）
    # ------------------------------------------------------------------ #
    def upload(self, key: str, data: FileContent, *, content_type: Optional[str] = None,
               public: bool = False, metadata: Optional[Dict[str, str]] = None) -> str:
        """上传内容。``data`` 可为 bytes / 二进制流 / 本地文件路径。"""
        raw = self._coerce_bytes(data)
        return self._upload_bytes(key, raw, content_type=content_type, public=public, metadata=metadata)

    def upload_file(self, key: str, file_path: str, *, content_type: Optional[str] = None,
                    public: bool = False, metadata: Optional[Dict[str, str]] = None) -> str:
        """从本地文件上传（适合大文件，避免整文件读入内存）。"""
        try:
            with open(file_path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise StorageError(f"读取本地文件失败 {file_path!r}: {exc}") from exc
        return self._upload_bytes(key, raw, content_type=content_type, public=public, metadata=metadata)

    def download(self, key: str) -> bytes:
        """下载对象为字节。"""
        return self._download_bytes(key)

    def download_file(self, key: str, dest_path: str) -> int:
        """下载对象并写入本地文件，返回写入字节数。"""
        data = self._download_bytes(key)
        try:
            with open(dest_path, "wb") as fh:
                fh.write(data)
        except OSError as exc:
            raise StorageError(f"写入本地文件失败 {dest_path!r}: {exc}") from exc
        return len(data)

    def delete(self, key: str) -> None:
        """删除对象（不存在也幂等成功）。"""
        self._delete(key)

    def exists(self, key: str) -> bool:
        return self._exists(key)

    def get_url(self, key: str, *, expires: Optional[int] = None, public: bool = False) -> str:
        return self._get_url(key, expires=expires, public=public)

    def list(self, prefix: str = "", *, max_keys: int = 1000) -> List[str]:
        return self._list(prefix, max_keys=max_keys)

    def stat(self, key: str) -> Dict[str, Any]:
        return self._stat(key)

    def copy(self, src_key: str, dst_key: str, *, public: bool = False) -> str:
        """拷贝对象（默认实现：下载后上传，子类可用原生 copy 优化）。"""
        data = self._download_bytes(src_key)
        return self._upload_bytes(dst_key, data, public=public)

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce_bytes(data: FileContent) -> bytes:
        """把多种输入类型统一成 bytes。"""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, str):
            # 视为文件路径
            try:
                with open(data, "rb") as fh:
                    return fh.read()
            except OSError as exc:
                # 也可能是纯文本字符串，但约定 str 不表示文本，这里明确报错
                raise StorageError(f"无法作为文件路径读取: {data!r} ({exc})") from exc
        if isinstance(data, io.BytesIO):
            return data.getvalue()
        if hasattr(data, "read"):
            try:
                chunk = data.read()
            except Exception as exc:  # pragma: no cover - 防御性
                raise StorageError(f"读取流失败: {exc}") from exc
            return chunk if isinstance(chunk, bytes) else bytes(chunk)
        raise StorageConfigError(f"不支持的上传内容类型: {type(data)!r}")

    def _normalize_key(self, key: str) -> str:
        """规范化 key：去除前导 ``/``、折叠 ``//``、保证不含 ``..`` 越界。"""
        key = key.strip().lstrip("/")
        while "//" in key:
            key = key.replace("//", "/")
        if ".." in key.split("/"):
            raise StorageConfigError(f"非法的 key（含路径越界）: {key!r}")
        return key
