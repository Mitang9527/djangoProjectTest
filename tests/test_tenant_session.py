"""阶段1 多租户核心链路：切租户重签 Token + UserSession 会话绑定（端到端回归）。

对齐参考项目（Fast-Vben-Admin）的 create_login_token / POST /tenants/switch：
  1. 登录建会话：UserSession 记录 token_jti 绑定 user+tenant，tenant_id=is_default 租户；
  2. 默认租户解析：无显式 tenant_id 时优先 is_default=True 成员；
  3. 切租户重签：旧会话被吊销（revoked_at），旧 access 立即 401，新 token 携带新 tenant_id；
  4. 刷新 Token 生成新会话（新 jti）；
  5. 登出吊销会话：对应 access 立即失效。

配套文件：scripts/verify_tenant_session.py（人工验证脚本，本文件为自动化回归）。
"""
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from system.saas.models import Role, Tenant, TenantMember
from system.users.models import User, UserSession


class TenantSwitchSessionTest(TestCase):
    """切租户重签 Token + 会话吊销链路。"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="tsuser", password="Pass123!", email="ts@v.com"
        )
        self.tenant_a = Tenant.objects.create(name="租户A", slug="ts_a")
        self.tenant_b = Tenant.objects.create(name="租户B", slug="ts_b")
        role = Role.objects.filter(slug="member", tenant__isnull=True).first()
        TenantMember.objects.create(
            tenant=self.tenant_a, user=self.user, role=role,
            is_active=True, is_default=True,
        )
        TenantMember.objects.create(
            tenant=self.tenant_b, user=self.user, role=role,
            is_active=True, is_default=False,
        )
        self.login_url = "/api/v1/users/jwt/login/"
        self.switch_url = "/api/v1/saas/me/switch-tenant/"
        self.refresh_url = "/api/v1/users/jwt/refresh/"
        self.info_url = "/api/v1/core/token/info/"
        self.logout_url = "/api/v1/users/logout/"

    def _login(self):
        c = APIClient()
        resp = c.post(
            self.login_url,
            {"username": "tsuser", "password": "Pass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        return data["access"], data["refresh"]

    def _switch(self, access, tenant_id):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        return c.post(self.switch_url, {"tenant_id": str(tenant_id)}, format="json")

    def _info_status(self, access):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        return c.get(self.info_url).status_code

    def test_login_creates_session_with_default_tenant(self):
        access, _ = self._login()
        at = AccessToken(access)
        self.assertEqual(str(at.get("tenant_id")), str(self.tenant_a.id))
        sess = UserSession.objects.filter(
            user=self.user, token_jti=at.get("jti")
        ).first()
        self.assertIsNotNone(sess)
        self.assertEqual(str(sess.tenant_id), str(self.tenant_a.id))
        self.assertIsNone(sess.revoked_at)
        # 默认租户解析：is_default 优先
        from system.users.serializers import resolve_login_tenant

        self.assertEqual(str(resolve_login_tenant(None, self.user)), str(self.tenant_a.id))

    def test_switch_tenant_resigns_token_and_revokes_old(self):
        old_access, _ = self._login()
        old_at = AccessToken(old_access)
        self.assertEqual(self._info_status(old_access), 200)

        resp = self._switch(old_access, self.tenant_b.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        new_access, new_refresh = data["access"], data["refresh"]
        self.assertIn("access", data)
        new_at = AccessToken(new_access)
        self.assertEqual(str(new_at.get("tenant_id")), str(self.tenant_b.id))

        # 旧 access 立即失效（会话已吊销）
        self.assertEqual(self._info_status(old_access), 401)
        old_sess = UserSession.objects.get(user=self.user, token_jti=old_at.get("jti"))
        self.assertIsNotNone(old_sess.revoked_at)

        # 新 access 可用且上下文为租户B
        self.assertEqual(self._info_status(new_access), 200)

        # 新会话记录存在且绑定租户B
        new_sess = UserSession.objects.get(user=self.user, token_jti=new_at.get("jti"))
        self.assertEqual(str(new_sess.tenant_id), str(self.tenant_b.id))

        # 刷新后新 access 仍可用（新 jti 会话）
        c = APIClient()
        r = c.post(self.refresh_url, {"refresh": new_refresh}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        refreshed = r.json()["data"]["access"]
        self.assertEqual(self._info_status(refreshed), 200)
        ratt = AccessToken(refreshed)
        self.assertTrue(
            UserSession.objects.filter(
                user=self.user, token_jti=ratt.get("jti")
            ).exists()
        )

    def test_switch_denied_for_non_member(self):
        access, _ = self._login()
        stranger = Tenant.objects.create(name="陌生租户", slug="ts_stranger")
        resp = self._switch(access, stranger.id)
        self.assertEqual(resp.status_code, 403)

    def test_logout_revokes_session(self):
        access, refresh = self._login()
        at = AccessToken(access)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        resp = c.post(self.logout_url, {"refresh": refresh}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        sess = UserSession.objects.get(user=self.user, token_jti=at.get("jti"))
        self.assertIsNotNone(sess.revoked_at)
        # 登出后 access 立即失效
        self.assertEqual(self._info_status(access), 401)

    def test_switch_to_global_view_keeps_session_valid(self):
        """传 null 清除上下文：不吊销会话，token 仍有效。"""
        access, _ = self._login()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        resp = c.post(self.switch_url, {"tenant_id": None}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._info_status(access), 200)


class UserSessionModelTest(TestCase):
    """UserSession 模型基础约束。"""

    def test_str_and_indexed_fields(self):
        u = User.objects.create_user(username="sessmodel", password="Pass123!")
        t = Tenant.objects.create(name="会话租户", slug="sess_t")
        sess = UserSession.objects.create(
            user=u, tenant=t, token_jti="jti_abc",
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        self.assertIn("sessmodel", str(sess))
        self.assertIn("jti_abc", str(sess))
