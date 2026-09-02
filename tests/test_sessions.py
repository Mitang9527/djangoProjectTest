"""会话管理 + 自助修改密码（账号安全闭环）。

覆盖：
  1. 会话列表：仅本人、含 is_current / 租户信息 / 上限 50；
  2. 踢单设备：吊销即该 access 401，当前设备不受影响；禁止吊销当前；越权 404；
  3. 踢其余：除当前外全部吊销；
  4. 自助改密：旧密码校验 / 强度校验 / 新密码≠旧密码 / 成功后旧 token 全端失效、
     当前设备重签免重登、其他设备会话被吊销、写 PASSWORD_CHANGE 审计。

关键机制（设计约束）：
  - 每次登录自增 token_version（单设备语义），因此「其他设备」会话需直接构造
    （同版本 access + 指定 jti 的 UserSession 记录），模拟同一版本下的多 token 并存；
  - refresh token 不校验会话，踢设备/改密必须靠 token_version 升版 + 会话吊销双保险。
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from system.core.models import AuditLog
from system.saas.models import Role, Tenant, TenantMember
from system.users.models import User, UserSession


class SessionBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="secuser", password="Pass123!", email="sec@v.com"
        )
        self.other = User.objects.create_user(
            username="otheruser", password="Pass123!", email="other@v.com"
        )
        self.tenant = Tenant.objects.create(name="会话租户", slug="sec_t")
        role = Role.objects.filter(slug="member", tenant__isnull=True).first()
        TenantMember.objects.create(
            tenant=self.tenant, user=self.user, role=role,
            is_active=True, is_default=True,
        )
        self.login_url = "/api/v1/users/jwt/login/"
        self.sessions_url = "/api/v1/users/sessions/"
        self.kick_url = self.sessions_url + "kick-others/"
        self.change_pwd_url = "/api/v1/users/change-password/"
        self.info_url = "/api/v1/core/token/info/"

    # ---------------------------------------------------------------
    # 工具
    # ---------------------------------------------------------------
    def _login(self, username="secuser", password="Pass123!"):
        resp = APIClient().post(
            self.login_url,
            {"username": username, "password": password},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        return data["access"], data["refresh"]

    def _client(self, access):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        return c

    def _info_status(self, access):
        return self._client(access).get(self.info_url).status_code

    def _make_device(self, user, jti, tenant=None, ip="10.0.0.1"):
        """构造「同版本下的另一个设备」：指定 jti 的 access + 对应会话记录。

        用当前 token_version 签发，模拟与当前登录同时有效的并发 token。
        """
        current_version = User.objects.get(pk=user.pk).token_version
        refresh = RefreshToken.for_user(user)
        refresh["token_version"] = current_version
        access = refresh.access_token
        access["jti"] = jti  # 覆盖默认 jti，与会话记录对齐
        session = UserSession.objects.create(
            user=user,
            tenant=tenant,
            token_jti=jti,
            ip=ip,
            user_agent="device-agent",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        return str(access), session


class SessionListTest(SessionBase):
    def test_list_shows_current_session_with_fields(self):
        access, _ = self._login()
        resp = self._client(access).get(self.sessions_url)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertEqual(data["count"], 1)
        s = data["sessions"][0]
        self.assertTrue(s["is_current"])
        self.assertEqual(s["tenant_id"], str(self.tenant.id))
        self.assertEqual(s["tenant_name"], "会话租户")
        # 输出字段齐备
        for key in ("id", "ip", "user_agent", "created_at", "expires_at",
                    "revoked_at", "is_current", "tenant_id", "tenant_name"):
            self.assertIn(key, s)

    def test_list_isolated_between_users(self):
        access_a, _ = self._login("secuser")
        access_b, _ = self._login("otheruser")
        # A 额外构造一台设备
        self._make_device(self.user, "jti-extra-a")
        resp_a = self._client(access_a).get(self.sessions_url)
        resp_b = self._client(access_b).get(self.sessions_url)
        self.assertEqual(resp_a.json()["data"]["count"], 2)
        self.assertEqual(resp_b.json()["data"]["count"], 1)
        # B 的列表里只有 B 自己的会话
        b_ids = {s["id"] for s in resp_b.json()["data"]["sessions"]}
        self.assertEqual(
            {str(s.id) for s in UserSession.objects.filter(user=self.other)},
            b_ids,
        )


class SessionKickTest(SessionBase):
    def test_destroy_revokes_other_device(self):
        access, _ = self._login()
        device_token, device_session = self._make_device(self.user, "jti-dev")
        # 踢之前：设备 token 有效
        self.assertEqual(self._info_status(device_token), 200)
        resp = self._client(access).delete(
            self.sessions_url + f"{device_session.id}/"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # 设备 token 立即失效，当前 token 不受影响
        self.assertEqual(self._info_status(device_token), 401)
        self.assertEqual(self._info_status(access), 200)
        # 列表只剩当前
        data = self._client(access).get(self.sessions_url).json()["data"]
        self.assertEqual(data["count"], 1)

    def test_destroy_current_forbidden(self):
        access, _ = self._login()
        current = UserSession.objects.get(user=self.user)
        resp = self._client(access).delete(self.sessions_url + f"{current.id}/")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "cannot_revoke_current")

    def test_destroy_other_users_session_404(self):
        _, session_a = self._make_device(self.user, "jti-a")
        access_b, _ = self._login("otheruser")
        resp = self._client(access_b).delete(
            self.sessions_url + f"{session_a.id}/"
        )
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertIsNone(UserSession.objects.get(pk=session_a.pk).revoked_at)

    def test_destroy_already_revoked_404(self):
        access, _ = self._login()
        device_token, device_session = self._make_device(self.user, "jti-dev2")
        self.assertEqual(
            self._client(access).delete(
                self.sessions_url + f"{device_session.id}/"
            ).status_code,
            200,
        )
        resp = self._client(access).delete(
            self.sessions_url + f"{device_session.id}/"
        )
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_kick_others_revokes_all_except_current(self):
        access, _ = self._login()
        t1, s1 = self._make_device(self.user, "jti-k1")
        t2, s2 = self._make_device(self.user, "jti-k2")
        self.assertEqual(self._info_status(t1), 200)
        self.assertEqual(self._info_status(t2), 200)
        resp = self._client(access).post(self.kick_url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["data"]["revoked"], 2)
        # 两个设备 token 全失效，当前 token 仍有效
        self.assertEqual(self._info_status(t1), 401)
        self.assertEqual(self._info_status(t2), 401)
        self.assertEqual(self._info_status(access), 200)
        # 列表只剩当前
        data = self._client(access).get(self.sessions_url).json()["data"]
        self.assertEqual(data["count"], 1)


class ChangePasswordTest(SessionBase):
    def test_wrong_old_password(self):
        access, _ = self._login()
        resp = self._client(access).post(
            self.change_pwd_url,
            {"old_password": "Wrong123!", "new_password": "NewPass#2026"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "old_password_wrong")

    def test_weak_new_password(self):
        access, _ = self._login()
        resp = self._client(access).post(
            self.change_pwd_url,
            {"old_password": "Pass123!", "new_password": "abc123"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_same_as_old_password(self):
        access, _ = self._login()
        resp = self._client(access).post(
            self.change_pwd_url,
            {"old_password": "Pass123!", "new_password": "Pass123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_success_reissues_tokens_and_old_password_dead(self):
        old_access, _ = self._login()
        resp = self._client(old_access).post(
            self.change_pwd_url,
            {"old_password": "Pass123!", "new_password": "NewPass#2026"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        # 旧 access 立即失效（token_version 已升）
        self.assertEqual(self._info_status(old_access), 401)
        # 新 access 可用（当前设备免重登）
        self.assertEqual(self._info_status(data["access"]), 200)
        # 旧密码无法再登录，新密码可以
        self.assertEqual(
            APIClient().post(
                self.login_url,
                {"username": "secuser", "password": "Pass123!"},
                format="json",
            ).status_code,
            401,
        )
        resp2 = APIClient().post(
            self.login_url,
            {"username": "secuser", "password": "NewPass#2026"},
            format="json",
        )
        self.assertEqual(resp2.status_code, 200, resp2.content)

    def test_change_password_revokes_all_other_sessions(self):
        old_access, _ = self._login()
        device_token, device_session = self._make_device(self.user, "jti-pwd")
        resp = self._client(old_access).post(
            self.change_pwd_url,
            {"old_password": "Pass123!", "new_password": "NewPass#2026"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # 改密后所有旧会话（含当前旧会话、其他设备）全部吊销
        revoked = UserSession.objects.filter(user=self.user, revoked_at__isnull=False)
        self.assertEqual(revoked.count(), 2)
        # 有效会话只剩重签的那 1 条
        active = UserSession.objects.filter(user=self.user, revoked_at__isnull=True)
        self.assertEqual(active.count(), 1)
        # 其他设备 token 也失效（版本戳 + 会话吊销双保险）
        self.assertEqual(self._info_status(device_token), 401)

    def test_change_password_writes_audit(self):
        access, _ = self._login()
        self._client(access).post(
            self.change_pwd_url,
            {"old_password": "Pass123!", "new_password": "NewPass#2026"},
            format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.user, action="PASSWORD_CHANGE", log_type="SENSITIVE",
            ).exists()
        )
