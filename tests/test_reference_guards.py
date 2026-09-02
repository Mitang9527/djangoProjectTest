"""参考完整性守卫（framework/db/reference_guards.py）端到端验证。

覆盖：
- 注册表：saas apps ready() 正确声明 Role/Permission/Department/Post/Tenant 的引用关系；
- 直调 assert_no_references：无引用放行 / 有引用抛 ReferenceConflict（文案含引用数量）；
- 便捷入口 raise_if_referenced：转 DRF 409 ReferenceConflictError；
- HTTP 409：删除被 Role.permissions M2M 引用的 Permission / 被 Role 引用的 Tenant → 409；
- 无引用删除 → 成功（CustomRenderer 将 DRF 204 统一转 200）。

约定：saas 接口前缀 /api/v1/saas/；超管（is_superuser=True）直通 ReadWriteTenantPermission。
"""
from django.test import TestCase
from rest_framework.test import APIClient
from system.saas.models import Department, Permission, Post, Role, Tenant, TenantMember
from system.users.models import User

from framework.db.reference_guards import (
    ReferenceConflict,
    ReferenceConflictError,
    assert_no_references,
    get_references,
    raise_if_referenced,
)
from tests.factories import AdminUserFactory, TenantFactory

PERMISSIONS_URL = "/api/v1/saas/permissions/"
TENANTS_URL = "/api/v1/saas/tenants/"


def _make_permission(slug):
    return Permission.objects.create(
        name=slug, slug=slug, module=Permission.Module.SYSTEM)


# ──────────────────────────────────────────────
# 注册表
# ──────────────────────────────────────────────

class ReferenceRegistryTest(TestCase):
    def test_role_references_registered(self):
        refs = get_references(Role)
        models = {ref[0] for ref in refs}
        # saas apps ready(): User.role / TenantMember.role / RoleDataScopeDepartment.role
        self.assertIn(User, models)
        self.assertIn(TenantMember, models)
        self.assertEqual(len(refs), 3)

    def test_permission_m2m_reference_registered(self):
        refs = get_references(Permission)
        self.assertEqual(len(refs), 1)
        ref_model, fields = refs[0]
        self.assertEqual(ref_model, Role.permissions.through)
        self.assertIn("permission", fields)

    def test_department_post_tenant_references_registered(self):
        self.assertTrue(get_references(Department))
        self.assertTrue(get_references(Post))
        self.assertEqual(len(get_references(Tenant)), 8)


# ──────────────────────────────────────────────
# 直调 API
# ──────────────────────────────────────────────

class AssertNoReferencesTest(TestCase):
    def test_no_refs_pass(self):
        tenant = TenantFactory()
        # 未创建任何引用 → 不抛
        assert_no_references(Tenant, tenant.pk)

    def test_tenant_referenced_by_role_raises(self):
        tenant = TenantFactory()
        Role.objects.create(tenant=tenant, name="角色", slug="role-x")
        with self.assertRaises(ReferenceConflict) as ctx:
            assert_no_references(Tenant, tenant.pk)
        self.assertIn("租户", str(ctx.exception))

    def test_permission_referenced_by_m2m_raises(self):
        perm = _make_permission("user.manage")
        role = Role.objects.create(name="管理员", slug="admin-role")
        role.permissions.add(perm)
        with self.assertRaises(ReferenceConflict):
            assert_no_references(Permission, perm.pk)

    def test_raise_if_referenced_converts_to_409_exception(self):
        perm = _make_permission("role.manage")
        role = Role.objects.create(name="角色", slug="role-y")
        role.permissions.add(perm)
        with self.assertRaises(ReferenceConflictError) as ctx:
            raise_if_referenced(Permission, perm.pk)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.default_code, "reference_conflict")


# ──────────────────────────────────────────────
# HTTP 层 409
# ──────────────────────────────────────────────

class ReferenceGuardHttpTest(TestCase):
    def setUp(self):
        self.admin = AdminUserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_delete_referenced_permission_409(self):
        perm = _make_permission("system.manage")
        Role.objects.create(name="管理员", slug="admin-role").permissions.add(perm)
        resp = self.client.delete(f"{PERMISSIONS_URL}{perm.pk}/")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "reference_conflict")
        self.assertTrue(Permission.objects.filter(pk=perm.pk).exists())

    def test_delete_unreferenced_permission_ok(self):
        perm = _make_permission("orphan.perm")
        resp = self.client.delete(f"{PERMISSIONS_URL}{perm.pk}/")
        # CustomRenderer 将 DRF 204 统一转 200
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(Permission.objects.filter(pk=perm.pk).exists())

    def test_delete_referenced_tenant_409(self):
        tenant = TenantFactory()
        Role.objects.create(tenant=tenant, name="角色", slug="role-z")
        resp = self.client.delete(f"{TENANTS_URL}{tenant.pk}/")
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "reference_conflict")
        self.assertTrue(Tenant.objects.filter(pk=tenant.pk).exists())

    def test_delete_unreferenced_tenant_ok(self):
        tenant = TenantFactory()
        resp = self.client.delete(f"{TENANTS_URL}{tenant.pk}/")
        # CustomRenderer 将 DRF 204 统一转 200
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(Tenant.objects.filter(pk=tenant.pk).exists())
