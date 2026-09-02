"""阶段3 多租户：组织（部门/岗位/成员岗位/角色数据权限）回归。

对齐参考项目（Fast-Vben-Admin）：
  - Department：树形（parent 自引用）、软归档删除（archived_at）、租户内 code 唯一、
    上级不能是自己/子孙/已归档节点、负责人必须是租户成员；
  - Post：租户内 code 唯一、软归档删除（有 UserPost 绑定拒绝）；
  - UserPost：成员岗位读写（PUT /members/{id}/posts 全量替换）；
  - Role.data_scope 5 态 + RoleDataScopeDepartment（custom 联动）+
    系统角色保护（不可取消系统标记/不可改 slug/不可删除已分配角色）；
  - TenantOrgService.apply_initialization_template 幂等建根部门 + 岗位种子。

配套文件：scripts/verify_phase3.py（人工验证脚本，本文件为自动化回归）。
"""
import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from system.saas.models import (
    Department,
    Post,
    Role,
    RoleDataScopeDepartment,
    Tenant,
    TenantMember,
    UserPost,
)
from system.saas.services import TenantOrgService
from system.users.models import User


# ============================================================
# 服务层：TenantOrgService
# ============================================================

class TenantOrgServiceTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="组织租户", slug="org_t")

    def test_apply_initialization_template_idempotent(self):
        """根部门 + 岗位种子幂等（多次调用不重复建）。"""
        root_dept = TenantOrgService.apply_initialization_template(self.tenant)
        self.assertIsNotNone(root_dept)
        root = Department.objects.filter(tenant=self.tenant, parent__isnull=True)
        self.assertEqual(root.count(), 1)
        self.assertEqual(root.first().code, "headquarters")
        self.assertEqual(Post.objects.filter(tenant=self.tenant).count(), 3)

        # 幂等：再次调用不新增
        TenantOrgService.apply_initialization_template(self.tenant)
        self.assertEqual(Department.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(Post.objects.filter(tenant=self.tenant).count(), 3)

    def test_is_descendant_department_cycle(self):
        """沿 parent 链向上追溯 + visited 防环。"""
        a = Department.objects.create(tenant=self.tenant, name="A", code="a")
        b = Department.objects.create(tenant=self.tenant, name="B", code="b", parent=a)
        c = Department.objects.create(tenant=self.tenant, name="C", code="c", parent=b)

        self.assertTrue(TenantOrgService.is_descendant_department(
            self.tenant, department_id=a.id, possible_descendant_id=c.id))
        self.assertTrue(TenantOrgService.is_descendant_department(
            self.tenant, department_id=a.id, possible_descendant_id=b.id))
        self.assertTrue(TenantOrgService.is_descendant_department(
            self.tenant, department_id=b.id, possible_descendant_id=c.id))
        self.assertFalse(TenantOrgService.is_descendant_department(
            self.tenant, department_id=c.id, possible_descendant_id=b.id))
        self.assertFalse(TenantOrgService.is_descendant_department(
            self.tenant, department_id=b.id, possible_descendant_id=a.id))

    def test_sync_role_custom_departments(self):
        """custom 全量替换 + 非 custom 清空。"""
        role = Role.objects.create(tenant=self.tenant, name="运营", slug="ops",
                                   data_scope=Role.DataScope.CUSTOM)
        d1 = Department.objects.create(tenant=self.tenant, name="一部", code="d1")
        d2 = Department.objects.create(tenant=self.tenant, name="二部", code="d2")
        d3 = Department.objects.create(tenant=self.tenant, name="三部", code="d3")

        TenantOrgService.sync_role_custom_departments(role, [str(d1.id), str(d2.id)])
        ids = set(TenantOrgService.get_custom_department_ids(role))
        self.assertEqual(ids, {d1.id, d2.id})

        # 全量替换：只剩 d3
        TenantOrgService.sync_role_custom_departments(role, [str(d3.id)])
        ids = set(TenantOrgService.get_custom_department_ids(role))
        self.assertEqual(ids, {d3.id})

        # 非 custom 清空
        role.data_scope = Role.DataScope.ALL
        role.save(update_fields=["data_scope"])
        TenantOrgService.sync_role_custom_departments(role, [str(d3.id)])
        self.assertEqual(list(TenantOrgService.get_custom_department_ids(role)), [])


# ============================================================
# 模型层：唯一约束 / 软归档
# ============================================================

class DepartmentModelTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="部门租户", slug="dept_t")
        self.other = Tenant.objects.create(name="另一租户", slug="dept_t2")

    def test_tenant_code_unique_constraint(self):
        Department.objects.create(tenant=self.tenant, name="总部", code="hq")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Department.objects.create(tenant=self.tenant, name="总部重复", code="hq")
        # 不同租户同 code 允许
        Department.objects.create(tenant=self.other, name="另一总部", code="hq")

    def test_soft_archive_sets_flags(self):
        d = Department.objects.create(tenant=self.tenant, name="待归档", code="arc")
        d.is_active = False
        d.archived_at = timezone.now()
        d.save(update_fields=["is_active", "archived_at"])
        d.refresh_from_db()
        self.assertIsNotNone(d.archived_at)
        self.assertFalse(d.is_active)

    def test_post_tenant_code_unique(self):
        Post.objects.create(tenant=self.tenant, name="经理", code="manager")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Post.objects.create(tenant=self.tenant, name="经理2", code="manager")
        Post.objects.create(tenant=self.other, name="经理", code="manager")

    def test_userpost_tenant_user_post_unique(self):
        user = User.objects.create_user(username="up_user", password="Pass123!")
        p = Post.objects.create(tenant=self.tenant, name="经理", code="manager")
        UserPost.objects.create(tenant=self.tenant, user=user, post=p)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                UserPost.objects.create(tenant=self.tenant, user=user, post=p)


# ============================================================
# 部门 API（租户注入 / 树校验 / 软归档）
# ============================================================

class DepartmentApiTest(TestCase):
    """JWT + X-Tenant-Id 走真实认证链路（同冒烟验证）。"""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="org_admin", email="org_admin@example.com", password="Pass123!",
        )
        self.tenant = Tenant.objects.create(name="部门API租户", slug="dept_api_t")
        self.member = User.objects.create_user(username="org_member", password="Pass123!")
        TenantMember.objects.create(tenant=self.tenant, user=self.member, is_active=True)
        from rest_framework_simplejwt.tokens import RefreshToken
        self.access = str(RefreshToken.for_user(self.user).access_token)
        self.base = "/api/v1/saas/departments"

    def _client(self):
        c = APIClient()
        c.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return c

    def _create_dept(self, client, name="测试部门", code="td", **extra):
        payload = {"name": name, "code": code}
        payload.update(extra)
        return client.post(f"{self.base}/", payload, format="json")

    def test_create_injects_tenant_from_context(self):
        """tenant 由请求上下文注入，客户端无需（也不应）传 tenant。"""
        c = self._client()
        resp = self._create_dept(c)
        self.assertEqual(resp.status_code, 201, resp.content)
        dept = Department.objects.get(code="td")
        self.assertEqual(dept.tenant_id, self.tenant.id)

    def test_code_unique_within_tenant(self):
        c = self._client()
        self.assertEqual(self._create_dept(c).status_code, 201)
        resp = self._create_dept(c, name="重复编码")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("编码", resp.json().get("errors", {}).get("code", [""])[0])

    def test_parent_cannot_be_self(self):
        c = self._client()
        dept = self._create_dept(c).json()["data"]
        resp = c.patch(f"{self.base}/{dept['id']}/", {"parent": dept["id"]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("自己", resp.json()["errors"]["parent"][0])

    def test_parent_cannot_be_descendant(self):
        c = self._client()
        a = self._create_dept(c, name="A", code="a").json()["data"]
        b = self._create_dept(c, name="B", code="b", parent=a["id"]).json()["data"]
        # 把 a 的父级设为 b（b 是 a 的子孙）→ 拒绝
        resp = c.patch(f"{self.base}/{a['id']}/", {"parent": b["id"]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("子部门", resp.json()["errors"]["parent"][0])

    def test_parent_archived_rejected(self):
        c = self._client()
        parent = self._create_dept(c, name="父", code="p").json()["data"]
        # 软归档父部门
        Department.objects.filter(id=parent["id"]).update(
            archived_at=timezone.now(), is_active=False)
        resp = self._create_dept(c, name="子", code="ch", parent=parent["id"])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("归档", resp.json()["errors"]["parent"][0])

    def test_leader_must_be_active_member(self):
        c = self._client()
        outsider = User.objects.create_user(username="outsider", password="Pass123!")
        resp = self._create_dept(c, leader_user=str(outsider.id))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("成员", resp.json()["errors"]["leader_user"][0])
        # 活跃成员可以
        resp = self._create_dept(c, name="有负责人", code="ld", leader_user=str(self.member.id))
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_list_excludes_archived(self):
        c = self._client()
        dept = self._create_dept(c).json()["data"]
        Department.objects.filter(id=dept["id"]).update(
            archived_at=timezone.now(), is_active=False)
        resp = c.get(f"{self.base}/")
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()["data"]["results"]]
        self.assertNotIn(dept["id"], ids)

    def test_destroy_soft_archive_with_protections(self):
        c = self._client()
        dept = self._create_dept(c).json()["data"]
        resp = c.delete(f"{self.base}/{dept['id']}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        obj = Department.objects.get(id=dept["id"])
        self.assertIsNotNone(obj.archived_at)
        self.assertFalse(obj.is_active)

        # 有子部门拒绝
        parent = self._create_dept(c, name="父", code="p2").json()["data"]
        self._create_dept(c, name="子", code="c2", parent=parent["id"])
        resp = c.delete(f"{self.base}/{parent['id']}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("子部门", resp.json()["errors"]["detail"])

        # 有活跃成员拒绝
        m_dept = self._create_dept(c, name="成员部门", code="md").json()["data"]
        TenantMember.objects.filter(user=self.member).update(department_id=m_dept["id"])
        resp = c.delete(f"{self.base}/{m_dept['id']}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("成员", resp.json()["errors"]["detail"])


# ============================================================
# 岗位 API + 成员岗位
# ============================================================

class PostApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="post_admin", email="post_admin@example.com", password="Pass123!",
        )
        self.tenant = Tenant.objects.create(name="岗位API租户", slug="post_api_t")
        from rest_framework_simplejwt.tokens import RefreshToken
        self.access = str(RefreshToken.for_user(self.user).access_token)
        self.base = "/api/v1/saas/posts"

    def _client(self):
        c = APIClient()
        c.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return c

    def test_create_injects_tenant_and_unique_code(self):
        c = self._client()
        resp = c.post(f"{self.base}/", {"name": "经理", "code": "manager"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        post = Post.objects.get(code="manager")
        self.assertEqual(post.tenant_id, self.tenant.id)
        # 重复编码
        resp = c.post(f"{self.base}/", {"name": "经理2", "code": "manager"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_destroy_soft_archive_rejects_userpost_binding(self):
        c = self._client()
        post = c.post(f"{self.base}/", {"name": "专员", "code": "officer"}, format="json").json()["data"]
        user = User.objects.create_user(username="bind_user", password="Pass123!")
        UserPost.objects.create(tenant=self.tenant, user=user, post_id=post["id"])
        resp = c.delete(f"{self.base}/{post['id']}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不能删除", resp.json()["errors"]["detail"])

        # 无绑定 → 软归档
        post2 = c.post(f"{self.base}/", {"name": "临时", "code": "tmp"}, format="json").json()["data"]
        resp = c.delete(f"{self.base}/{post2['id']}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        obj = Post.objects.get(id=post2["id"])
        self.assertIsNotNone(obj.archived_at)


class MemberPostsApiTest(TestCase):
    """PUT /members/{id}/posts 全量替换 + 跨租户校验。"""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="mp_admin", email="mp_admin@example.com", password="Pass123!",
        )
        self.tenant = Tenant.objects.create(name="成员岗位租户", slug="mp_t")
        self.member_user = User.objects.create_user(username="mp_member", password="Pass123!")
        self.member = TenantMember.objects.create(
            tenant=self.tenant, user=self.member_user, is_active=True)
        self.p1 = Post.objects.create(tenant=self.tenant, name="经理", code="manager")
        self.p2 = Post.objects.create(tenant=self.tenant, name="开发", code="developer")
        self.other_tenant = Tenant.objects.create(name="外部租户", slug="mp_t2")
        self.p_other = Post.objects.create(tenant=self.other_tenant, name="外岗", code="ext")
        from rest_framework_simplejwt.tokens import RefreshToken
        self.access = str(RefreshToken.for_user(self.user).access_token)
        self.base = f"/api/v1/saas/tenant-members/{self.member.id}/posts/"

    def _client(self):
        c = APIClient()
        c.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return c

    def test_put_full_replace_and_get(self):
        c = self._client()
        resp = c.put(self.base, {"post_ids": [str(self.p1.id), str(self.p2.id)]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        codes = {r["post_code"] for r in resp.json()["data"]}
        self.assertEqual(codes, {"manager", "developer"})

        # 全量替换为只剩 p2
        resp = c.put(self.base, {"post_ids": [str(self.p2.id)]}, format="json")
        self.assertEqual(resp.status_code, 200)
        codes = {r["post_code"] for r in resp.json()["data"]}
        self.assertEqual(codes, {"developer"})
        self.assertEqual(UserPost.objects.filter(user=self.member_user).count(), 1)

        # GET 返回当前列表
        resp = c.get(self.base)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]), 1)

    def test_other_tenant_post_rejected(self):
        c = self._client()
        resp = c.put(self.base, {"post_ids": [str(self.p_other.id)]}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不属于", resp.json()["errors"]["detail"])


# ============================================================
# 角色数据权限 API
# ============================================================

class RoleApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="role_admin", email="role_admin@example.com", password="Pass123!",
        )
        self.tenant = Tenant.objects.create(name="角色租户", slug="role_t")
        self.dept = Department.objects.create(tenant=self.tenant, name="一部", code="d1")
        from rest_framework_simplejwt.tokens import RefreshToken
        self.access = str(RefreshToken.for_user(self.user).access_token)
        self.base = "/api/v1/saas/roles"

    def _client(self):
        c = APIClient()
        c.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return c

    def test_create_custom_scope_syncs_departments(self):
        c = self._client()
        resp = c.post(f"{self.base}/", {
            "tenant": str(self.tenant.id),
            "name": "区域运营",
            "slug": "region_ops",
            "data_scope": "custom",
            "custom_department_ids": [str(self.dept.id)],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        role = Role.objects.get(slug="region_ops")
        self.assertEqual(role.data_scope, "custom")
        links = RoleDataScopeDepartment.objects.filter(role=role)
        self.assertEqual(links.count(), 1)
        self.assertEqual(str(links.first().department_id), str(self.dept.id))

    def test_custom_scope_requires_departments(self):
        c = self._client()
        resp = c.post(f"{self.base}/", {
            "tenant": str(self.tenant.id),
            "name": "空自定义",
            "slug": "empty_custom",
            "data_scope": "custom",
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("必须指定", resp.json()["errors"]["custom_department_ids"][0])

    def test_system_role_protected(self):
        # 系统角色 tenant=None：需在无租户上下文（全局后台）下访问
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        sys_role = Role.objects.create(
            tenant=None, name="超级管理员", slug="super-admin", is_system=True)
        # 不可取消系统标记
        resp = c.patch(f"{self.base}/{sys_role.id}/", {"is_system": False}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("系统角色", resp.json()["errors"]["is_system"][0])
        # 不可改 slug
        resp = c.patch(f"{self.base}/{sys_role.id}/", {"slug": "hacked"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("标识", resp.json()["errors"]["slug"][0])
        # 不可删除
        resp = c.delete(f"{self.base}/{sys_role.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("系统角色", resp.json()["errors"]["detail"])

    def test_assigned_role_not_deletable(self):
        c = self._client()
        role = Role.objects.create(tenant=self.tenant, name="已分配", slug="assigned")
        holder = User.objects.create_user(username="role_holder", password="Pass123!")
        TenantMember.objects.create(tenant=self.tenant, user=holder, role=role, is_active=True)
        resp = c.delete(f"{self.base}/{role.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("分配", resp.json()["errors"]["detail"])
