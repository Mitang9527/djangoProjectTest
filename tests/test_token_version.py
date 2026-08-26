"""token_version 机制端到端验证（无外部依赖，使用 SQLite 测试库）。

覆盖：
1. 登录写入 token_version claim，且受保护接口可用；
2. 重新登录使旧 token 立即失效（401）；
3. 改密（UserManageSerializer）使旧 token 立即失效；
4. 刷新 token 时 token_version 被复制到新 access。
"""
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from urllib.parse import parse_qs, urlparse

from system.users.models import User
from system.users.serializers import UserManageSerializer
from system.users.services import LoginService, TokenService
from framework.drf.sliding_jwt import SlidingJWTAuthentication


class TokenVersionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tvuser", password="pass123", email="tv@v.com"
        )
        self.login_url = "/api/v1/users/jwt/login/"
        self.refresh_url = "/api/v1/users/jwt/refresh/"
        self.info_url = "/api/v1/core/token/info/"

    def _login(self):
        c = APIClient()
        resp = c.post(
            self.login_url,
            {"username": "tvuser", "password": "pass123"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        payload = resp.json()["data"]
        return payload["access"], payload["refresh"]

    def _info_status(self, access):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        return c.get(self.info_url).status_code

    def test_login_sets_version_and_token_works(self):
        access, _refresh = self._login()
        at = AccessToken(access)
        self.assertEqual(at.get("token_version"), 1)
        self.assertEqual(self._info_status(access), 200)

    def test_relogin_invalidates_old_token(self):
        old_access, _ = self._login()
        new_access, _ = self._login()
        self.assertEqual(AccessToken(new_access).get("token_version"), 2)
        # 旧 token 立即 401
        self.assertEqual(self._info_status(old_access), 401)

    def test_password_change_invalidates_old_token(self):
        access, _ = self._login()
        # login 已将 DB 的 token_version 置为 1，同步内存实例后再改密
        self.user.refresh_from_db()
        ser = UserManageSerializer(
            instance=self.user, data={"password": "newpass123"}, partial=True
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, 2)
        # 改密后旧 token 立即 401
        self.assertEqual(self._info_status(access), 401)

    def test_refresh_copies_version(self):
        access, refresh = self._login()
        c = APIClient()
        resp = c.post(self.refresh_url, {"refresh": refresh}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        new_access = resp.json()["data"]["access"]
        self.assertEqual(AccessToken(new_access).get("token_version"), 1)


class TokenVersionCoverageTest(TestCase):
    """覆盖 token_version 在所有「用户会话」JWT 签发点的接入情况。

    确保除标准 jwt/login 之外，其余 5 个登录签发点
    （UserLoginView / LoginService.login / LoginService.jwt_login /
    DemoLoginView / OIDC 回调）以及滑动续期均正确写入 token_version，
    使旧 token 在重登 / 改密后立即失效。
    """

    def _info_status(self, access):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        return c.get("/api/v1/core/token/info/").status_code

    def test_user_login_view_sets_version_and_relogin_invalidates(self):
        User.objects.create_user(username="ulv", password="Pass123!", email="ulv@v.com")
        c = APIClient()
        r1 = c.post("/api/v1/users/login/", {"username": "ulv", "password": "Pass123!"}, format="json")
        self.assertEqual(r1.status_code, 200, r1.content)
        old = r1.json()["data"]["access"]
        self.assertEqual(AccessToken(old).get("token_version"), 1)

        r2 = c.post("/api/v1/users/login/", {"username": "ulv", "password": "Pass123!"}, format="json")
        new = r2.json()["data"]["access"]
        self.assertEqual(AccessToken(new).get("token_version"), 2)
        # 旧 token 立即失效
        self.assertEqual(self._info_status(old), 401)

    def test_loginservice_login_sets_version(self):
        u = User.objects.create_user(username="lsv", password="Pass123!", email="lsv@v.com")
        res = LoginService.login(username="lsv", password="Pass123!")
        self.assertNotIn("error", res)
        self.assertEqual(AccessToken(res["tokens"]["access"]).get("token_version"), 1)
        u.refresh_from_db()
        self.assertEqual(u.token_version, 1)

    def test_loginservice_jwt_login_sets_version(self):
        u = User.objects.create_user(username="lsj", password="Pass123!", email="lsj@v.com")
        res = TokenService.jwt_login(username="lsj", password="Pass123!")
        self.assertNotIn("error", res)
        self.assertEqual(AccessToken(res["access"]).get("token_version"), 1)

    @override_settings(ALLOW_DEMO_LOGIN=True)
    def test_demo_login_sets_version(self):
        from unittest import mock

        with mock.patch("system.core.auth._maybe_quota", return_value=None):
            u, _ = User.objects.get_or_create(username="demouser")
            c = APIClient()
            resp = c.post("/api/v1/core/demo-login/", {"username": "demouser"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json().get("data", resp.json())
        self.assertEqual(AccessToken(data["access"]).get("token_version"), 1)

    def test_oidc_callback_sets_version(self):
        try:
            from system.users.oidc import OIDCCallbackView
        except ImportError:
            self.skipTest("mozilla-django-oidc 未安装，跳过 OIDC 覆盖测试")
        u = User.objects.create_user(username="oidcuser", password="Pass123!", email="oidc@v.com")
        view = OIDCCallbackView()
        view.user = u
        url = view.success_url
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(AccessToken(qs["access"][0]).get("token_version"), 1)
        u.refresh_from_db()
        self.assertEqual(u.token_version, 1)

    def test_sliding_renewal_copies_version(self):
        # 验证滑动续期生成的新 access 正确复制 token_version 声明
        u = User.objects.create_user(username="slv", password="Pass123!", email="slv@v.com")
        c = APIClient()
        r = c.post("/api/v1/users/jwt/login/", {"username": "slv", "password": "Pass123!"}, format="json")
        access = r.json()["data"]["access"]
        src = AccessToken(access)
        self.assertEqual(src.get("token_version"), 1)
        new_token = SlidingJWTAuthentication._issue_new_access_token(src)
        self.assertEqual(new_token.get("token_version"), 1)
