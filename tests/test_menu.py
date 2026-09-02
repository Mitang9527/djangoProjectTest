"""平台级动态菜单（Menu）+ 按钮级权限端到端验证。

覆盖：
- 迁移播种：默认菜单树存在（工作台目录 / AI 生成业务 / 管理后台[system.manage] /
  AI 创作 / 我的控制台 + 按钮权限 user.manage / role.manage）；
- 管理 CRUD（/api/v1/core/menus/）：仅超级管理员可访问，普通用户 403、未登录 401；
  按钮节点必填 permission（400）、增删改查成功；
- my-menus（/api/v1/core/my-menus/，登录即可）：
    普通用户仅见「无权限码」菜单，未授权节点整体丢弃（父不可见 → 子树不出现）；
    授予 system.manage + user.manage 后管理后台与其按钮下发，权限码集合正确；
    超管直通全量 + 权限码返回 Permission 表全部 slug；
    未登录 401。

约定：菜单模型在 system.core.models.Menu，接口前缀 /api/v1/core/。
"""
from django.test import TestCase
from rest_framework.test import APIClient
from system.core.models import Menu
from system.saas.models import Permission, Role, TenantMember

from tests.factories import AdminUserFactory, TenantFactory, UserFactory

MENUS_URL = "/api/v1/core/menus/"
MY_MENUS_URL = "/api/v1/core/my-menus/"


def _client(user, tenant_id=None):
    c = APIClient()
    c.force_authenticate(user=user)
    if tenant_id is not None:
        c.credentials(HTTP_X_TENANT_ID=str(tenant_id))
    return c


def _grant(user, tenant, *slugs):
    """建角色 + 授予 slugs + 绑定租户成员（与 test_dicts 同款）。"""
    key = "_".join(slugs).replace(".", "_")
    role = Role.objects.create(tenant=tenant, name=f"角色-{key}", slug=f"role_{key}")
    for s in slugs:
        perm, _ = Permission.objects.get_or_create(
            slug=s, defaults={"name": s, "module": Permission.Module.SYSTEM})
        role.permissions.add(perm)
    TenantMember.objects.create(tenant=tenant, user=user, role=role, is_active=True)
    return role


def _menu_names(nodes):
    """递归取树节点 name 列表（含子节点）。"""
    names = []
    for n in nodes:
        names.append(n["name"])
        names.extend(_menu_names(n.get("children") or []))
    return names


# ──────────────────────────────────────────────
# 迁移播种
# ──────────────────────────────────────────────

class MenuSeedTest(TestCase):
    def test_default_menus_seeded(self):
        self.assertTrue(Menu.objects.exists())
        # 目录 + 菜单 + 按钮示例
        self.assertTrue(Menu.objects.filter(name="工作台", type="directory").exists())
        self.assertTrue(Menu.objects.filter(name="AI 生成业务", type="menu").exists())
        admin = Menu.objects.filter(name="管理后台", type="menu").first()
        self.assertIsNotNone(admin)
        self.assertEqual(admin.permission, "system.manage")
        # 按钮权限码必填（种子示例）
        btn = Menu.objects.filter(type="button").first()
        self.assertIsNotNone(btn)
        self.assertTrue(btn.permission)

    def test_button_without_permission_rejected_by_serializer(self):
        # 序列化器校验：按钮必填权限码（管理端 400 由 Http 测试覆盖，这里直测校验器）
        from system.core.serializers import MenuSerializer
        s = MenuSerializer(data={"name": "x", "type": "button"})
        self.assertFalse(s.is_valid())
        self.assertIn("permission", s.errors)


# ──────────────────────────────────────────────
# 管理 CRUD（仅超管）
# ──────────────────────────────────────────────

class MenuCrudTest(TestCase):
    def setUp(self):
        self.admin = AdminUserFactory()
        self.user = UserFactory()
        self.admin_client = _client(self.admin)
        self.user_client = _client(self.user)

    def test_requires_admin(self):
        resp = APIClient().get(MENUS_URL)
        self.assertEqual(resp.status_code, 401)
        resp = self.user_client.get(MENUS_URL)
        self.assertEqual(resp.status_code, 403, resp.content)
        resp = self.user_client.post(MENUS_URL, {"name": "x"}, format="json")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_admin_list_and_detail(self):
        resp = self.admin_client.get(MENUS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.json()["data"]["results"]
        self.assertGreater(len(results), 0)

        node = results[0]
        resp = self.admin_client.get(f"{MENUS_URL}{node['id']}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["id"], node["id"])

    def test_admin_create_menu_node(self):
        resp = self.admin_client.post(MENUS_URL, {
            "name": "报表中心",
            "route_name": "report",
            "path": "/report",
            "component": "report",
            "type": "menu",
            "sort": 50,
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["data"]["name"], "报表中心")

    def test_admin_create_button_requires_permission(self):
        resp = self.admin_client.post(MENUS_URL, {
            "name": "导出按钮", "type": "button",
        }, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("permission", resp.json()["errors"])

    def test_admin_update_and_delete(self):
        node = Menu.objects.create(name="临时", type="menu")
        resp = self.admin_client.patch(
            f"{MENUS_URL}{node.id}/", {"name": "改名"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["name"], "改名")

        resp = self.admin_client.delete(f"{MENUS_URL}{node.id}/")
        # CustomRenderer 将 DRF 204 统一转 200
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(Menu.objects.filter(pk=node.id).exists())


# ──────────────────────────────────────────────
# my-menus（按角色权限码过滤下发）
# ──────────────────────────────────────────────

class MyMenusTest(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.tenant = TenantFactory()
        self.client = _client(self.user)

    def test_requires_auth(self):
        resp = APIClient().get(MY_MENUS_URL)
        self.assertEqual(resp.status_code, 401)

    def test_normal_user_sees_only_open_menus(self):
        resp = self.client.get(MY_MENUS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        names = _menu_names(data["menus"])
        # 无权限码节点可见
        self.assertIn("工作台", names)
        self.assertIn("AI 生成业务", names)
        self.assertIn("AI 创作", names)
        # 绑定 system.manage 的“管理后台”被过滤（其子树按钮一并丢弃）
        self.assertNotIn("管理后台", names)
        self.assertNotIn("用户管理", names)
        # 无任何权限码
        self.assertEqual(data["permissions"], [])

    def test_user_with_permissions_sees_authorized_subtree(self):
        _grant(self.user, self.tenant, "system.manage", "user.manage")
        resp = self.client.get(MY_MENUS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        names = _menu_names(data["menus"])
        self.assertIn("管理后台", names)
        self.assertIn("用户管理", names)      # 按钮随父菜单下发（v-permission 用）
        self.assertNotIn("角色管理", names)   # 未授权按钮不出现
        self.assertEqual(sorted(data["permissions"]), ["system.manage", "user.manage"])

    def test_super_admin_sees_all_and_all_permissions(self):
        admin = AdminUserFactory()
        Permission.objects.get_or_create(
            slug="menu.manage", defaults={"name": "菜单管理", "module": Permission.Module.SYSTEM})
        resp = _client(admin).get(MY_MENUS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        names = _menu_names(data["menus"])
        self.assertIn("管理后台", names)
        self.assertIn("用户管理", names)
        self.assertIn("角色管理", names)
        # 超管权限码 = Permission 表全部 slug
        all_slugs = set(Permission.objects.filter(is_active=True).values_list("slug", flat=True))
        self.assertEqual(set(data["permissions"]), all_slugs)

    def test_inactive_menu_excluded(self):
        Menu.objects.create(name="隐藏菜单", type="menu", is_active=False)
        resp = self.client.get(MY_MENUS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn("隐藏菜单", _menu_names(resp.json()["data"]["menus"]))
