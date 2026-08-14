"""对象存储抽象层单测（本地后端，不依赖外部云资源）"""

import io
import os
import sys
import tempfile
import unittest

# 让测试能找到项目根
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from framework.storage import (
    get_storage,
    clear_cache,
    upload,
    download,
    delete,
    exists,
    get_url,
    list_objects,
    stat,
    LocalStorageBackend,
    StorageBackend,
    StorageNotFoundError,
)
from framework.storage.base import StorageBackend as _ABC
from framework.storage.exceptions import StorageError


class LocalBackendTest(unittest.TestCase):
    """验证本地后端与便捷函数（不连任何云）。"""

    def setUp(self):
        clear_cache()
        self.tmp = tempfile.mkdtemp(prefix="oss_test_")
        self.backend = LocalStorageBackend(self.tmp, media_url="media/")

    def tearDown(self):
        # 清理：直接清理临时目录
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_is_storage_backend(self):
        self.assertIsInstance(self.backend, StorageBackend)
        self.assertTrue(issubclass(LocalStorageBackend, _ABC))

    def test_upload_download_bytes(self):
        url = self.backend.upload("a/b.txt", b"hello", content_type="text/plain", public=True)
        self.assertTrue(url.endswith("/a/b.txt"))
        self.assertEqual(self.backend.download("a/b.txt"), b"hello")

    def test_upload_stream_and_file(self):
        self.backend.upload("s.bin", io.BytesIO(b"stream"))
        self.assertEqual(self.backend.download("s.bin"), b"stream")

        src = os.path.join(self.tmp, "_src.bin")
        with open(src, "wb") as fh:
            fh.write(b"fromfile")
        self.backend.upload_file("f.bin", src)
        self.assertEqual(self.backend.download("f.bin"), b"fromfile")

    def test_exists_and_delete_idempotent(self):
        self.backend.upload("x.txt", b"x")
        self.assertTrue(self.backend.exists("x.txt"))
        self.backend.delete("x.txt")
        self.assertFalse(self.backend.exists("x.txt"))
        # 删除不存在的对象不应抛错（幂等）
        self.backend.delete("x.txt")

    def test_not_found(self):
        with self.assertRaises((StorageNotFoundError, StorageError)):
            self.backend.download("nope.txt")

    def test_list_and_stat(self):
        self.backend.upload("p/1.txt", b"1")
        self.backend.upload("p/2.txt", b"2")
        keys = self.backend.list("p/")
        self.assertIn("p/1.txt", keys)
        self.assertIn("p/2.txt", keys)
        self.assertEqual(self.backend.stat("p/1.txt")["size"], 1)

    def test_get_url_public_vs_signed(self):
        self.backend.upload("u.txt", b"u", public=True)
        self.assertTrue(self.backend.get_url("u.txt", public=True).endswith("/u.txt"))
        # 私有对象：返回带签名/路径的 URL，不应抛错
        self.assertTrue(self.backend.get_url("u.txt", public=False, expires=300))

    def test_key_normalization_blocks_traversal(self):
        with self.assertRaises(StorageError):
            self.backend.upload("../escape.txt", b"bad")


class ConvenienceApiTest(unittest.TestCase):
    """验证模块级便捷函数走默认后端（local）。"""

    def setUp(self):
        clear_cache()
        # 便捷函数依赖 Django settings.OSS_CONFIG，这里最小化配置即可（无需全局 env）
        import django
        from django.conf import settings as _s
        if not _s.configured:
            _s.configure(
                BASE_DIR=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                MEDIA_URL="media/",
                OSS_CONFIG={"backend": "local", "local_root": tempfile.mkdtemp(prefix="oss_cfg_")},
            )
        os.environ.setdefault("OSS_BACKEND", "local")

    def test_convenience_roundtrip(self):
        url = upload("cv/demo.txt", b"cv", public=True)
        self.assertIsInstance(url, str)
        self.assertEqual(download("cv/demo.txt"), b"cv")
        self.assertTrue(exists("cv/demo.txt"))
        self.assertIn("cv/demo.txt", list_objects("cv/"))
        self.assertEqual(stat("cv/demo.txt")["size"], 2)
        delete("cv/demo.txt")
        self.assertFalse(exists("cv/demo.txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
