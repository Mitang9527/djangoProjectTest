"""
Django Storage 桥接
====================

提供 :class:`DjangoOSSStorage`，继承 ``django.core.files.storage.Storage``，
可直接作为 ``FileField(upload_to=..., storage=oss_storage)`` 的 storage，
从而让 Django 模型字段的附件自动落到 OSS/S3/本地。

用法示例::

    from framework.storage.django_storage import DjangoOSSStorage
    oss_storage = DjangoOSSStorage()

    class Avatar(models.Model):
        image = models.ImageField(upload_to="avatars/", storage=oss_storage)

注意：对于大文件/流式场景，建议直接用 ``get_storage().upload_file()`` 而非 FileField，
本桥接主要服务于既有 Django 模型附件的平滑迁移。
"""

from __future__ import annotations

from typing import Optional

from django.core.files.storage import Storage

from .factory import get_storage


class DjangoOSSStorage(Storage):
    """把 Django FileField 操作映射到 framework.storage 后端。"""

    def __init__(self, backend: Optional[object] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._backend = backend

    @property
    def backend(self):
        if self._backend is None:
            self._backend = get_storage()
        return self._backend

    def _open(self, name, mode="rb"):
        from django.core.files.base import ContentFile
        data = self.backend.download(name)
        return ContentFile(data, name=name)

    def _save(self, name, content):
        data = content.read()
        self.backend.upload(name, data, content_type=getattr(content, "content_type", None))
        return name

    def exists(self, name) -> bool:
        try:
            return self.backend.exists(name)
        except Exception:
            return False

    def delete(self, name):
        try:
            self.backend.delete(name)
        except Exception:
            pass

    def url(self, name) -> str:
        return self.backend.get_url(name, public=True)

    def size(self, name) -> int:
        try:
            return self.backend.stat(name).get("size", 0)
        except Exception:
            return 0

    def get_available_name(self, name, max_length=None):
        return name
