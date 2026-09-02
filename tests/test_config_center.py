"""系统设置中心（配置中心）端到端验证。

覆盖：
- get_config_value 修复：返回真实值（不再 500）；key 不存在 → value=None/exists=False；
  key 为空 → 400；类型按 config_type 解析（int/boolean/json）；
- 分组管理 get_config_groups：按 Category 顺序返回全部分组（含空组），
  分组含 code/name/description，配置项含 key/value/name/config_type 等明细；
- 写操作权限（平台级管控）：set / delete / reload 仅超管，普通用户 403；
- set 新增必填 name（400）、更新与删除 round-trip；
- get_public_configs：仅返回 is_public=True 且激活的配置。

约定：接口前缀 /api/v1/saas/config-center/。
"""
from django.test import TestCase
from rest_framework.test import APIClient
from system.saas.models import GlobalConfig

from tests.factories import AdminUserFactory, UserFactory

GET_URL = "/api/v1/saas/config-center/get/"
GROUPS_URL = "/api/v1/saas/config-center/groups/"
SET_URL = "/api/v1/saas/config-center/set/"
DELETE_URL = "/api/v1/saas/config-center/delete/"
RELOAD_URL = "/api/v1/saas/config-center/reload/"
PUBLIC_URL = "/api/v1/saas/config-center/public/"


def _cfg(key, value="1", config_type="string", category="system", **kw):
    defaults = {
        "name": f"配置-{key}", "value": value, "config_type": config_type,
        "category": category, "is_active": True, "is_public": False,
    }
    defaults.update(kw)
    return GlobalConfig.objects.create(key=key, **defaults)


class GetConfigValueTest(TestCase):
    """bug 修复：get_config_value 必须返回真实值而非 500。"""

    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.client.force_authenticate(self.user)

    def test_returns_real_value(self):
        _cfg("site.name", value="My Platform")
        resp = self.client.get(GET_URL, {"key": "site.name"})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertEqual(data["key"], "site.name")
        self.assertEqual(data["value"], "My Platform")
        self.assertTrue(data["exists"])

    def test_missing_key_returns_none(self):
        resp = self.client.get(GET_URL, {"key": "ghost.key"})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertIsNone(data["value"])
        self.assertFalse(data["exists"])

    def test_empty_key_returns_400(self):
        resp = self.client.get(GET_URL)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["errors"]["detail"], "key 参数不能为空")

    def test_parses_by_config_type(self):
        _cfg("int.val", value="42", config_type="integer")
        _cfg("bool.val", value="true", config_type="boolean")
        _cfg("json.val", value='{"a": 1}', config_type="json")
        for key, expected in [("int.val", 42), ("bool.val", True), ("json.val", {"a": 1})]:
            resp = self.client.get(GET_URL, {"key": key})
            self.assertEqual(resp.json()["data"]["value"], expected, key)


class ConfigGroupsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(UserFactory())

    def test_groups_in_category_order_with_meta(self):
        resp = self.client.get(GROUPS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        groups = resp.json()["data"]
        # Category 声明顺序：system / feature / business / security（含空组）
        self.assertEqual([g["code"] for g in groups],
                         ["system", "feature", "business", "security"])
        for g in groups:
            self.assertIn("name", g)
            self.assertIn("description", g)
            self.assertIn("configs", g)

    def test_configs_grouped_correctly(self):
        _cfg("system.a", category="system")
        _cfg("sec.a", category="security")
        resp = self.client.get(GROUPS_URL)
        groups = {g["code"]: g for g in resp.json()["data"]}
        sys_keys = {c["key"] for c in groups["system"]["configs"]}
        sec_keys = {c["key"] for c in groups["security"]["configs"]}
        self.assertIn("system.a", sys_keys)
        self.assertIn("sec.a", sec_keys)
        self.assertNotIn("sec.a", sys_keys)
        # 空组也要出现（前端分组布局稳定）
        self.assertEqual(groups["business"]["configs"], [])

    def test_config_item_fields(self):
        _cfg("site.name", name="站点名称", value="P", description="站点名称说明", is_public=True)
        resp = self.client.get(GROUPS_URL)
        groups = {g["code"]: g for g in resp.json()["data"]}
        item = next(c for c in groups["system"]["configs"] if c["key"] == "site.name")
        self.assertEqual(item["name"], "站点名称")
        self.assertEqual(item["value"], "P")
        self.assertEqual(item["config_type"], "string")
        self.assertEqual(item["description"], "站点名称说明")
        self.assertTrue(item["is_public"])
        self.assertTrue(item["is_active"])


class ConfigWritePermissionTest(TestCase):
    """平台级管控：set / delete / reload 仅超管。"""

    def setUp(self):
        self.user = UserFactory()
        self.admin = AdminUserFactory()
        self.user_client = APIClient()
        self.user_client.force_authenticate(self.user)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)

    def test_normal_user_forbidden_on_writes(self):
        for method, url, data in [
            ("post", SET_URL, {"key": "k", "value": "v", "name": "n"}),
            ("delete", DELETE_URL, None),
            ("post", RELOAD_URL, {}),
        ]:
            resp = getattr(self.user_client, method)(url, data, format="json") if data is not None \
                else getattr(self.user_client, method)(url)
            self.assertEqual(resp.status_code, 403, f"{method} {url}: {resp.content}")

    def test_anonymous_forbidden(self):
        resp = APIClient().post(SET_URL, {"key": "k", "value": "v", "name": "n"}, format="json")
        self.assertEqual(resp.status_code, 401)

    def test_admin_set_create_requires_name(self):
        resp = self.admin_client.post(SET_URL, {"key": "new.key", "value": "v"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["errors"]["detail"], "新增配置时 name 不能为空")

    def test_admin_set_round_trip(self):
        # 新增
        resp = self.admin_client.post(SET_URL, {
            "key": "round.trip", "value": 99, "name": "往返", "config_type": "integer",
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        cfg = GlobalConfig.objects.get(key="round.trip")
        self.assertEqual(cfg.value, "99")
        # 更新
        resp = self.admin_client.post(SET_URL, {"key": "round.trip", "value": 100}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        cfg.refresh_from_db()
        self.assertEqual(cfg.value, "100")
        # 历史被记录
        from system.saas.models import ConfigHistory
        self.assertTrue(ConfigHistory.objects.filter(config_key="round.trip").exists())

    def test_admin_delete(self):
        _cfg("del.key", value="x")
        resp = self.admin_client.delete(f"{DELETE_URL}?key=del.key")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(GlobalConfig.objects.filter(key="del.key").exists())

    def test_delete_missing_key(self):
        resp = self.admin_client.delete(DELETE_URL)
        self.assertEqual(resp.status_code, 400)
        resp = self.admin_client.delete(f"{DELETE_URL}?key=ghost.key")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["errors"]["detail"], "配置不存在")

    def test_admin_reload(self):
        resp = self.admin_client.post(RELOAD_URL, {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["status"], "ok")


class PublicConfigsTest(TestCase):
    def test_public_only(self):
        _cfg("pub.a", value="1", is_public=True)
        _cfg("priv.b", value="2", is_public=False)
        resp = APIClient().get(PUBLIC_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertIn("pub.a", data)
        self.assertNotIn("priv.b", data)
