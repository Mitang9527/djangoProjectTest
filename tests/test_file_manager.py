"""FileAsset 管理端点 + 租户配额用量看板端到端验证。

覆盖：
- 权限矩阵：未登录 401；普通用户 403；授予 file.view → 列表/详情/usage 200；
  仅 file.view 无 file.manage → DELETE/restore 403；file.manage → 软删/恢复成功；
- 列表筛选：tenant / category / deleted（'1' 仅已删、'0' 仅未删、不传全部）/ keyword；
- restore：恢复已删资产 200（is_deleted=False）；恢复未删资产 400（code=not_deleted）；
- usage 看板（file-assets/usage/）：缺租户上下文 404（tenant_required）、
  租户不存在 404（tenant_not_found）、正常返回 get_usage 结构（members/file_assets/storage_bytes/plan）；
- 序列化器：url 为 MEDIA_URL 相对地址、size_display 可读文本、tenant_name/user_name/category_display 透出。

约定：接口前缀 /api/v1/core/；DELETE 经 CustomRenderer 统一返回 200。
"""
import os
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from system.core.models import FileAsset
from system.saas.models import Permission, Role, TenantMember

from tests.factories import TenantFactory, UserFactory

ASSETS_URL = "/api/v1/core/file-assets/"
USAGE_URL = "/api/v1/core/file-assets/usage/"


def _client(user, tenant_id=None):
    c = APIClient()
    c.force_authenticate(user=user)
    if tenant_id is not None:
        c.credentials(HTTP_X_TENANT_ID=str(tenant_id))
    return c


def _grant(user, tenant, *slugs):
    """建角色 + 授予 slugs + 绑定租户成员（与 test_menu / test_dicts 同款）。"""
    key = "_".join(slugs).replace(".", "_")
    role = Role.objects.create(tenant=tenant, name=f"角色-{key}", slug=f"role_{key}")
    for s in slugs:
        perm, _ = Permission.objects.get_or_create(
            slug=s, defaults={"name": s, "module": Permission.Module.SYSTEM})
        role.permissions.add(perm)
    TenantMember.objects.create(tenant=tenant, user=user, role=role, is_active=True)
    return role


def _asset(tenant=None, user=None, **kw):
    defaults = {
        "category": FileAsset.Category.DOCUMENT,
        "file_name": "a.txt",
        "file_path": "/media/test/a.txt",
        "file_size": 1024,
        "content_type": "text/plain",
    }
    defaults.update(kw)
    return FileAsset.objects.create(tenant=tenant, user=user, **defaults)


# ──────────────────────────────────────────────
# 权限矩阵
# ──────────────────────────────────────────────

class FileAssetPermissionTest(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.tenant = TenantFactory()
        self.asset = _asset(tenant=self.tenant, user=self.user)

    def test_requires_auth(self):
        resp = APIClient().get(ASSETS_URL)
        self.assertEqual(resp.status_code, 401)
        resp = APIClient().get(USAGE_URL)
        self.assertEqual(resp.status_code, 401)

    def test_normal_user_forbidden(self):
        client = _client(self.user)
        resp = client.get(ASSETS_URL)
        self.assertEqual(resp.status_code, 403, resp.content)
        resp = client.get(USAGE_URL)
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_file_view_grants_read(self):
        _grant(self.user, self.tenant, "file.view")
        client = _client(self.user)
        resp = client.get(ASSETS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["results"][0]["id"], str(self.asset.id))
        resp = client.get(f"{ASSETS_URL}{self.asset.id}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = client.get(f"{USAGE_URL}?tenant={self.tenant.id}")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_file_manage_required_for_write(self):
        _grant(self.user, self.tenant, "file.view")  # 只有读权限
        client = _client(self.user)
        resp = client.delete(f"{ASSETS_URL}{self.asset.id}/")
        self.assertEqual(resp.status_code, 403, resp.content)
        resp = client.post(f"{ASSETS_URL}{self.asset.id}/restore/")
        self.assertEqual(resp.status_code, 403, resp.content)
        # 资产未被改动
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.is_deleted)

    def test_file_manage_soft_delete_and_restore(self):
        _grant(self.user, self.tenant, "file.view", "file.manage")
        client = _client(self.user)
        # 软删（CustomRenderer 将 DRF 204 统一转 200）
        resp = client.delete(f"{ASSETS_URL}{self.asset.id}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.asset.refresh_from_db()
        self.assertTrue(self.asset.is_deleted)
        # 恢复
        resp = client.post(f"{ASSETS_URL}{self.asset.id}/restore/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["is_deleted"], False)
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.is_deleted)


# ──────────────────────────────────────────────
# 列表筛选 + restore 语义
# ──────────────────────────────────────────────

class FileAssetFilterTest(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.tenant_a = TenantFactory()
        self.tenant_b = TenantFactory()
        _grant(self.user, self.tenant_a, "file.view", "file.manage")
        self.client = _client(self.user)
        self.asset_a = _asset(tenant=self.tenant_a, file_name="report-2026.pdf", category=FileAsset.Category.DOCUMENT)
        self.asset_b = _asset(tenant=self.tenant_a, file_name="cover.png", category=FileAsset.Category.IMAGE, content_type="image/png")
        self.asset_c = _asset(tenant=self.tenant_b, file_name="other.txt", category=FileAsset.Category.DOCUMENT)

    def test_filter_by_tenant(self):
        resp = self.client.get(ASSETS_URL, {"tenant": self.tenant_a.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        ids = {r["id"] for r in resp.json()["data"]["results"]}
        self.assertEqual(ids, {str(self.asset_a.id), str(self.asset_b.id)})

    def test_filter_by_category(self):
        resp = self.client.get(ASSETS_URL, {"category": "image"})
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.asset_b.id))

    def test_filter_deleted(self):
        self.asset_a.is_deleted = True
        self.asset_a.save(update_fields=["is_deleted"])
        # '0' = 仅未删
        resp = self.client.get(ASSETS_URL, {"deleted": "0"})
        ids = {r["id"] for r in resp.json()["data"]["results"]}
        self.assertNotIn(str(self.asset_a.id), ids)
        # '1' = 仅已删
        resp = self.client.get(ASSETS_URL, {"deleted": "1"})
        ids = {r["id"] for r in resp.json()["data"]["results"]}
        self.assertEqual(ids, {str(self.asset_a.id)})
        # 不传 = 全部
        resp = self.client.get(ASSETS_URL)
        self.assertEqual(resp.json()["data"]["count"], 3)

    def test_filter_keyword(self):
        resp = self.client.get(ASSETS_URL, {"keyword": "report"})
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.asset_a.id))

    def test_restore_non_deleted_returns_400(self):
        resp = self.client.post(f"{ASSETS_URL}{self.asset_a.id}/restore/")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "not_deleted")


# ──────────────────────────────────────────────
# 配额用量看板
# ──────────────────────────────────────────────

class FileAssetsUsageTest(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.tenant = TenantFactory()
        _grant(self.user, self.tenant, "file.view")
        self.client = _client(self.user)

    def test_missing_tenant_context(self):
        resp = self.client.get(USAGE_URL)
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "tenant_required")

    def test_tenant_not_found(self):
        resp = self.client.get(USAGE_URL, {"tenant": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "tenant_not_found")

    def test_usage_structure(self):
        _asset(tenant=self.tenant, user=self.user, file_name="a.txt", file_size=2048)
        resp = self.client.get(USAGE_URL, {"tenant": self.tenant.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertEqual(data["tenant_id"], str(self.tenant.id))
        self.assertEqual(data["tenant_name"], self.tenant.name)
        self.assertEqual(data["file_assets"], 1)
        self.assertEqual(data["storage_bytes"], 2048)
        self.assertIn("members", data)
        self.assertIsNotNone(data["plan"])


# ──────────────────────────────────────────────
# 序列化器字段
# ──────────────────────────────────────────────

@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="test_media_mgr_"))
class FileAssetSerializerTest(TestCase):
    def test_fields(self):
        from system.core.serializers import FileAssetSerializer
        user = UserFactory()
        tenant = TenantFactory()
        rel_path = os.path.join("uploads", "a.txt")
        asset = _asset(
            tenant=tenant, user=user,
            file_name="a.txt",
            file_path=os.path.join(str(settings.MEDIA_ROOT), rel_path),
            file_size=1024,
        )
        data = FileAssetSerializer(asset).data
        media_url = str(settings.MEDIA_URL).strip("/")
        expected_url = f"{media_url}/{rel_path.replace(os.sep, '/')}" if media_url else rel_path.replace(os.sep, "/")
        self.assertEqual(data["url"], expected_url)
        self.assertEqual(data["size_display"], "1.0 KB")
        self.assertEqual(data["tenant_name"], tenant.name)
        self.assertEqual(data["user_name"], user.username)
        self.assertEqual(data["category_display"], "文档")
        # 相对地址不含反斜杠（跨平台 URL 规范）
        self.assertNotIn("\\", data["url"])
