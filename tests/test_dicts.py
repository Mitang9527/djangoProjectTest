"""字典管理（DictType + DictItem）端到端验证（对齐 Fast-Vben-Admin dictionaries）。

覆盖：
- 公开读端点 /api/v1/core/dicts/<code>/items/：
    全局字典读取、租户合并（全局项 + 私有项）、租户隔离（他租户私有字典 404）、
    未知/停用 code 404、停用项排除、未登录 401；
- 缓存：读回填、二次读命中、缓存键按租户隔离、写操作（create/update/delete）失效、
    Redis 异常降级直查库；
- 权限：dict.view 可读不可写、dict.manage 可写、无权限 403、超管直通、
    无租户上下文仅超管可建全局字典、跨租户 type 拒绝、tenant 字段只读。

约定：所有响应经 CustomRenderer 五字段包装，成功列表在 data["results"]，
错误码在 errors["error_code"]。
"""
import json
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from system.core.models import DictItem, DictType
from system.saas.models import Permission, Role, TenantMember
from tests.factories import AdminUserFactory, TenantFactory, UserFactory

PUBLIC_URL = "/api/v1/core/dicts/{code}/items/"
TYPES_URL = "/api/v1/core/dicts/types/"
ITEMS_URL = "/api/v1/core/dicts/items/"


def _client(user, tenant_id=None):
    c = APIClient()
    c.force_authenticate(user=user)
    if tenant_id is not None:
        c.credentials(HTTP_X_TENANT_ID=str(tenant_id))
    return c


def _grant(user, tenant, *slugs):
    """建角色 + 授予 slugs + 绑定租户成员。"""
    key = "_".join(slugs).replace(".", "_")
    role = Role.objects.create(
        tenant=tenant, name=f"角色-{key}", slug=f"role_{key}")
    for s in slugs:
        perm, _ = Permission.objects.get_or_create(
            slug=s, defaults={"name": s, "module": Permission.Module.SYSTEM})
        role.permissions.add(perm)
    TenantMember.objects.create(tenant=tenant, user=user, role=role, is_active=True)
    return role


class _FakeRedis:
    """内存版 RedisClient（dict 缓存用到的 get/set/delete）。"""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ex=None, **kwargs):
        self._data[key] = value
        return True

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                n += 1
        return n


def _patch_redis(fake):
    return mock.patch("framework.cache.redis_client.get_redis", return_value=fake)


# ──────────────────────────────────────────────
# 公开读端点
# ──────────────────────────────────────────────

class DictPublicReadTest(TestCase):
    def setUp(self):
        self.tenant_a = TenantFactory()
        self.tenant_b = TenantFactory()
        self.user = UserFactory()
        self.client = _client(self.user)

    def test_requires_auth(self):
        resp = APIClient().get(PUBLIC_URL.format(code="gender"))
        self.assertEqual(resp.status_code, 401)

    def test_global_dict_read_without_tenant(self):
        t = DictType.objects.create(name="性别", code="gender")
        DictItem.objects.create(type=t, label="男", value="1", sort=1)
        DictItem.objects.create(type=t, label="女", value="2", sort=2)
        resp = self.client.get(PUBLIC_URL.format(code="gender"))
        self.assertEqual(resp.status_code, 200, resp.content)
        items = resp.json()["data"]
        self.assertEqual([i["value"] for i in items], ["1", "2"])
        self.assertEqual(items[0]["type_code"], "gender")
        self.assertEqual(items[0]["type_name"], "性别")

    def test_unknown_code_404(self):
        resp = self.client.get(PUBLIC_URL.format(code="nope"))
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "dict_not_found")

    def test_inactive_type_404(self):
        DictType.objects.create(name="停用", code="off", is_active=False)
        resp = self.client.get(PUBLIC_URL.format(code="off"))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["errors"]["error_code"], "dict_not_found")

    def test_inactive_items_excluded(self):
        t = DictType.objects.create(name="状态", code="status")
        DictItem.objects.create(type=t, label="启用", value="1", is_active=True)
        DictItem.objects.create(type=t, label="停用", value="0", is_active=False)
        items = self.client.get(PUBLIC_URL.format(code="status")).json()["data"]
        self.assertEqual([i["value"] for i in items], ["1"])

    def test_tenant_reads_global_dict(self):
        t = DictType.objects.create(name="性别", code="gender")
        DictItem.objects.create(type=t, label="男", value="1")
        resp = _client(self.user, self.tenant_a.id).get(PUBLIC_URL.format(code="gender"))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.json()["data"]), 1)

    def test_tenant_merges_global_and_private_items(self):
        t = DictType.objects.create(name="性别", code="gender")
        DictItem.objects.create(type=t, label="男", value="1", sort=1)
        DictItem.objects.create(type=t, label="女", value="2", sort=2)
        # 租户 A 私有项挂在全局类型下（参考语义：全局项 + 租户私有项合并）
        DictItem.objects.create(type=t, tenant=self.tenant_a, label="保密", value="9", sort=9)

        items_a = _client(self.user, self.tenant_a.id).get(
            PUBLIC_URL.format(code="gender")).json()["data"]
        self.assertEqual([i["value"] for i in items_a], ["1", "2", "9"])

        # 租户 B 看不到 A 的私有项
        items_b = _client(self.user, self.tenant_b.id).get(
            PUBLIC_URL.format(code="gender")).json()["data"]
        self.assertEqual([i["value"] for i in items_b], ["1", "2"])

    def test_tenant_private_dict_isolation(self):
        t = DictType.objects.create(name="内部编码", code="internal", tenant=self.tenant_a)
        DictItem.objects.create(type=t, tenant=self.tenant_a, label="A", value="a")

        # 租户 B 访问 A 的私有字典 → 404（类型不可见即视为不存在）
        resp = _client(self.user, self.tenant_b.id).get(PUBLIC_URL.format(code="internal"))
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "dict_not_found")

        # 租户 A 正常读取
        resp = _client(self.user, self.tenant_a.id).get(PUBLIC_URL.format(code="internal"))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"][0]["label"], "A")


# ──────────────────────────────────────────────
# 缓存：回填 / 命中 / 失效 / 降级
# ──────────────────────────────────────────────

class DictCacheTest(TestCase):
    def setUp(self):
        self.tenant_a = TenantFactory()
        self.tenant_b = TenantFactory()
        self.superuser = AdminUserFactory()
        self.client = _client(self.superuser)
        self.type = DictType.objects.create(name="性别", code="gender")
        DictItem.objects.create(type=self.type, label="男", value="1", sort=1)
        self.cache_key = "dict:items:global:gender"
        self.fake = _FakeRedis()

    def _read(self):
        return self.client.get(PUBLIC_URL.format(code="gender"))

    def test_read_populates_cache(self):
        with _patch_redis(self.fake):
            resp = self._read()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn(self.cache_key, self.fake._data)
        payload = json.loads(self.fake._data[self.cache_key])
        self.assertEqual(payload[0]["value"], "1")

    def test_second_read_serves_from_cache(self):
        with _patch_redis(self.fake):
            self._read()
            # 篡改缓存为标记值 + 删光 DB 记录 → 二次读必须命中缓存
            self.fake._data[self.cache_key] = json.dumps([{"marker": True}])
            DictItem.objects.all().delete()
            resp = self._read()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"], [{"marker": True}])

    def test_cache_key_isolated_by_tenant(self):
        DictItem.objects.create(
            type=self.type, tenant=self.tenant_a,
            label="私有", value="p", sort=5)
        tenant_a_key = f"dict:items:{self.tenant_a.id}:gender"
        tenant_b_key = f"dict:items:{self.tenant_b.id}:gender"

        with _patch_redis(self.fake):
            _client(self.superuser, self.tenant_a.id).get(PUBLIC_URL.format(code="gender"))
            _client(self.superuser, self.tenant_b.id).get(PUBLIC_URL.format(code="gender"))

        self.assertIn(tenant_a_key, self.fake._data)
        self.assertIn(tenant_b_key, self.fake._data)
        self.assertEqual(len(json.loads(self.fake._data[tenant_a_key])), 2)  # 全局 + 私有
        self.assertEqual(len(json.loads(self.fake._data[tenant_b_key])), 1)  # 仅全局

    def test_create_item_invalidates_cache(self):
        with _patch_redis(self.fake):
            self._read()
            self.assertIn(self.cache_key, self.fake._data)
            resp = self.client.post(ITEMS_URL, {
                "type": str(self.type.id), "label": "新增", "value": "3",
            }, format="json")
            self.assertEqual(resp.status_code, 201, resp.content)
            self.assertNotIn(self.cache_key, self.fake._data)

    def test_update_item_invalidates_cache(self):
        item = DictItem.objects.create(type=self.type, label="旧", value="old")
        with _patch_redis(self.fake):
            self._read()
            self.assertIn(self.cache_key, self.fake._data)
            resp = self.client.patch(f"{ITEMS_URL}{item.id}/", {"label": "新"}, format="json")
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertNotIn(self.cache_key, self.fake._data)

    def test_delete_item_invalidates_cache(self):
        item = DictItem.objects.create(type=self.type, label="临时", value="tmp")
        with _patch_redis(self.fake):
            self._read()
            self.assertIn(self.cache_key, self.fake._data)
            resp = self.client.delete(f"{ITEMS_URL}{item.id}/")
            self.assertEqual(resp.status_code, 200, resp.content)  # CustomRenderer 语义化为 200
            self.assertNotIn(self.cache_key, self.fake._data)

    def test_redis_exception_degrades_to_db(self):
        class _BoomRedis:
            def get(self, key):
                raise RuntimeError("redis down")
            def set(self, *a, **k):
                raise RuntimeError("redis down")
            def delete(self, *a, **k):
                raise RuntimeError("redis down")

        with mock.patch("framework.cache.redis_client.get_redis", return_value=_BoomRedis()):
            resp = self._read()
        self.assertEqual(resp.status_code, 200, resp.content)  # 直查库，缓存层不阻断


# ──────────────────────────────────────────────
# 权限：dict.view / dict.manage / 超管
# ──────────────────────────────────────────────

class DictPermissionTest(TestCase):
    def setUp(self):
        self.tenant = TenantFactory()
        self.other_tenant = TenantFactory()
        self.superuser = AdminUserFactory()
        self.viewer = UserFactory()
        self.manager = UserFactory()
        self.member = UserFactory()  # 无任何权限
        _grant(self.viewer, self.tenant, "dict.view")
        _grant(self.manager, self.tenant, "dict.view", "dict.manage")

    def test_list_requires_dict_view(self):
        resp = _client(self.member, self.tenant.id).get(TYPES_URL)
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_viewer_can_read_not_write(self):
        c = _client(self.viewer, self.tenant.id)
        resp = c.get(TYPES_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = c.post(TYPES_URL, {"name": "X", "code": "x"}, format="json")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_manager_can_write_and_read(self):
        c = _client(self.manager, self.tenant.id)
        resp = c.post(TYPES_URL, {"name": "优先级", "code": "priority"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()["data"]
        self.assertEqual(body["code"], "priority")
        self.assertEqual(body["tenant"], str(self.tenant.id))
        self.assertEqual(body["item_count"], 0)

        resp = c.get(TYPES_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        codes = [r["code"] for r in resp.json()["data"]["results"]]
        self.assertIn("priority", codes)

    def test_superuser_bypasses_permissions(self):
        resp = _client(self.superuser, self.tenant.id).get(TYPES_URL)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_global_type_create_requires_superadmin(self):
        # 非超管且无租户上下文 → 拒绝
        resp = _client(self.manager).post(
            TYPES_URL, {"name": "全局", "code": "global_x"}, format="json")
        self.assertEqual(resp.status_code, 403, resp.content)

        # 超管可建全局字典（tenant=null）
        resp = _client(self.superuser).post(
            TYPES_URL, {"name": "全局", "code": "global_x"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIsNone(resp.json()["data"]["tenant"])

    def test_item_create_rejects_foreign_type(self):
        foreign = DictType.objects.create(name="他租户", code="foreign", tenant=self.other_tenant)
        c = _client(self.manager, self.tenant.id)
        resp = c.post(ITEMS_URL, {
            "type": str(foreign.id), "label": "x", "value": "x",
        }, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        # CustomRenderer 直透 serializer.errors：errors["type"] 为字符串而非列表
        self.assertIn("字典类型不存在", resp.json()["errors"]["type"])

    def test_item_create_sets_current_tenant(self):
        t = DictType.objects.create(name="性别", code="gender", tenant=self.tenant)
        c = _client(self.manager, self.tenant.id)
        resp = c.post(ITEMS_URL, {
            "type": str(t.id), "label": "男", "value": "1",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["data"]["tenant"], str(self.tenant.id))

    def test_tenant_field_is_read_only(self):
        # 客户端试图指定归属租户 → 被忽略，实际归属当前请求租户
        c = _client(self.manager, self.tenant.id)
        resp = c.post(TYPES_URL, {
            "name": "劫持", "code": "hijack",
            "tenant": str(self.other_tenant.id),
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["data"]["tenant"], str(self.tenant.id))

        # 更新同样不可迁移归属
        type_id = resp.json()["data"]["id"]
        resp = c.patch(f"{TYPES_URL}{type_id}/", {"tenant": str(self.other_tenant.id)},
                       format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["tenant"], str(self.tenant.id))
