"""文件资产登记表（FileAsset）端到端验证。

覆盖：
- 上传成功登记资产（tenant / user / category / file_size / content_type）；
- 无租户上下文上传仍登记（tenant=None）；
- TenantProfileService.get_usage 接入真实统计（file_assets / storage_bytes）；
- 软删资产（is_deleted=True）从 usage 与配额统计排除；
- 租户配额执行：max_file_assets 超限 429（code=file_quota_exceeded）且落盘文件被清理；
- max_storage_mb 超限 429（code=storage_quota_exceeded）。
"""
import os
import shutil
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from system.core.models import FileAsset
from system.saas.services import TenantProfileService
from tests.factories import PlanFactory, TenantFactory, UserFactory

UPLOAD_URL = "/api/v1/core/upload/file/"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="test_media_"))
class FileAssetUploadTest(TestCase):
    """上传链路资产登记 + 配额执行。"""

    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.client.force_authenticate(self.user)
        self.plan = PlanFactory(max_file_assets=100, max_storage_mb=1024)
        self.tenant = TenantFactory(plan=self.plan)

    def _upload(self, name="a.txt", content=b"hello", tenant_id=None):
        f = SimpleUploadedFile(name, content, content_type="text/plain")
        headers = {}
        if tenant_id is not None:
            headers["HTTP_X_TENANT_ID"] = str(tenant_id)
        return self.client.post(UPLOAD_URL, {"file": f}, format="multipart", **headers)

    def test_upload_registers_asset(self):
        resp = self._upload(tenant_id=self.tenant.id)
        self.assertEqual(resp.status_code, 201, resp.content)
        asset = FileAsset.objects.get()
        self.assertEqual(asset.tenant_id, self.tenant.id)
        self.assertEqual(asset.user_id, self.user.id)
        self.assertEqual(asset.category, FileAsset.Category.DOCUMENT)
        self.assertEqual(asset.file_name, "a.txt")
        self.assertEqual(asset.file_size, 5)
        self.assertEqual(asset.content_type, "text/plain")
        self.assertFalse(asset.is_deleted)
        # 落盘文件确实存在
        self.assertTrue(os.path.exists(asset.file_path))

    def test_upload_without_tenant_still_registers(self):
        resp = self._upload()
        self.assertEqual(resp.status_code, 201, resp.content)
        asset = FileAsset.objects.get()
        self.assertIsNone(asset.tenant)
        self.assertEqual(asset.category, FileAsset.Category.DOCUMENT)

    def test_usage_counts_real_assets(self):
        self._upload(name="a.txt", content=b"abc", tenant_id=self.tenant.id)
        self._upload(name="b.txt", content=b"12345", tenant_id=self.tenant.id)
        usage = TenantProfileService.get_usage(self.tenant)
        self.assertEqual(usage["file_assets"], 2)
        self.assertEqual(usage["storage_bytes"], 8)

    def test_soft_deleted_assets_excluded_from_usage(self):
        self._upload(name="a.txt", content=b"abc", tenant_id=self.tenant.id)
        asset = FileAsset.objects.get()
        asset.is_deleted = True
        asset.save(update_fields=["is_deleted"])
        usage = TenantProfileService.get_usage(self.tenant)
        self.assertEqual(usage["file_assets"], 0)
        self.assertEqual(usage["storage_bytes"], 0)

    def test_file_count_quota_exceeded(self):
        self.plan.max_file_assets = 1
        self.plan.save(update_fields=["max_file_assets"])
        first = self._upload(name="a.txt", content=b"abc", tenant_id=self.tenant.id)
        self.assertEqual(first.status_code, 201)
        # 第二条命中数量配额：429 且刚落盘的文件被清理
        second = self._upload(name="b.txt", content=b"12345", tenant_id=self.tenant.id)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["errors"]["error_code"], "file_quota_exceeded")
        self.assertEqual(FileAsset.objects.filter(tenant=self.tenant).count(), 1)
        # 磁盘上不残留被拒文件
        media_root = str(settings.MEDIA_ROOT)
        leftovers = [os.path.join(root, f) for root, _, files in os.walk(media_root) for f in files if "b.txt" in f]
        self.assertEqual(leftovers, [])

    def test_storage_quota_exceeded(self):
        self.plan.max_storage_mb = 0  # 任何文件都超限（0 MB）
        self.plan.save(update_fields=["max_storage_mb"])
        resp = self._upload(name="a.txt", content=b"abc", tenant_id=self.tenant.id)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["errors"]["error_code"], "storage_quota_exceeded")
        self.assertEqual(FileAsset.objects.filter(tenant=self.tenant).count(), 0)


class FileAssetModelTest(TestCase):
    """模型层：级联删除与软删标记语义。"""

    def test_tenant_cascade_deletes_assets(self):
        tenant = TenantFactory()
        FileAsset.objects.create(
            tenant=tenant, category=FileAsset.Category.DOCUMENT,
            file_name="a.txt", file_path="/tmp/x/a.txt", file_size=3,
        )
        self.assertEqual(FileAsset.objects.filter(tenant=tenant).count(), 1)
        tenant.delete()
        self.assertEqual(FileAsset.objects.count(), 0)
