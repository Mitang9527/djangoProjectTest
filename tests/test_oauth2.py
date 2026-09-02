"""OAuth2 第三方登录（Authorization Code + PKCE）端到端验证。

覆盖：
  1. authorize：匿名生成授权链接（PKCE S256 挑战 + state 存 Redis 一次性）、
     redirect_uri 动态生成 / 表配置优先、provider 不存在 404、Redis 不可用 503；
  2. callback：换 token → userinfo → 自动建号 / email 匹配绑定 / 用户名冲突 +i、
     签发 JWT（token_version + 会话 + 登录日志）、access 可调受保护接口、
     state 一次性（重复使用 400）、provider 不匹配 400、code 缺失 400、
     第三方拒绝 400、token 交换失败 502、userinfo 缺标识 502、
     AUTO_BIND_EMAIL / AUTO_CREATE_USER 关闭时 unbound 400、
     FRONTEND_URL 配置时 302 重定向带 token；
  3. bind：已登录绑定成功、重复绑定他人 409、未认证 401。

说明：测试环境 Redis 不可达（_NullRedis 降级），注入内存 FakeRedisClient；
HTTP 调用 monkeypatch OAuth2Service._http_post_form / _http_get_json 避免真实网络。
"""
import pickle
import urllib.parse

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from system.users.models import OAuthAccount, OAuthProvider, User, UserSession
from system.users.oauth2 import OAuth2Error, OAuth2Service
from tests.factories import UserFactory

AUTH_URL = "/api/v1/users/oauth/github/authorize/"
CALLBACK_URL = "/api/v1/users/oauth/github/callback/"
BIND_URL = "/api/v1/users/oauth/github/bind/"

GITHUB_PROFILE = {
    "id": 123456,
    "login": "octocat",
    "name": "Octo Cat",
    "email": "octocat@example.com",
    "avatar_url": "https://avatars.githubusercontent.com/u/123456",
}


class FakeRedisClient:
    """内存 Redis 客户端（测试用），接口对齐 RedisClient 封装"""

    def __init__(self):
        self._data = {}  # key -> pickle bytes

    def set(self, key, value, ex=None, **kwargs):
        self._data[key] = pickle.dumps(value)
        return True

    def get(self, key, default=None):
        raw = self._data.get(key)
        return pickle.loads(raw) if raw is not None else default

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                n += 1
        return n

    def get_client(self):
        return self

    def ping(self):
        return True

    def eval(self, script, numkeys, key):
        """模拟 _GETDEL_SCRIPT：取走即删"""
        return self._data.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedisClient()
    monkeypatch.setattr(OAuth2Service, "_redis_ready", lambda: True)
    monkeypatch.setattr(OAuth2Service, "_client", lambda: fake)
    return fake


@pytest.fixture
def provider(db):
    return OAuthProvider.objects.create(
        name="github",
        display_name="GitHub",
        client_id="client-123",
        client_secret="secret-456",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
        pkce_enabled=True,
        is_active=True,
    )


@pytest.fixture
def mock_http(monkeypatch):
    """拦截 token 交换与 userinfo 拉取（避免真实网络）。

    token_error 传入 OAuth2Error 实例（模拟服务层转换后的结果，
    真实 HTTP 异常已在 _http_post_form/_http_get_json 内转换）。
    """
    def _set(token_data=None, profile=GITHUB_PROFILE, token_error=None, info_error=None):
        def _post_form(url, data):
            if token_error:
                raise token_error
            return token_data or {"access_token": "gho_token_abc", "token_type": "bearer"}

        def _get_json(url, headers=None):
            if info_error:
                raise info_error
            return dict(profile)

        monkeypatch.setattr(OAuth2Service, "_http_post_form", staticmethod(_post_form))
        monkeypatch.setattr(OAuth2Service, "_http_get_json", staticmethod(_get_json))
    return _set


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestOAuth2Authorize:
    """授权链接生成"""

    def test_build_authorize(self, client, provider, fake_redis):
        resp = client.get(AUTH_URL)
        assert resp.status_code == 200, resp.content
        data = resp.json()["data"]
        assert data["state"]
        assert data["expires_in"] == OAuth2Service._state_ttl()
        # PKCE S256 挑战 + 授权码参数
        url = data["authorize_url"]
        assert "response_type=code" in url
        assert "client_id=client-123" in url
        assert "state=" + data["state"] in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "scope=read%3Auser+user%3Aemail" in url
        # redirect_uri 动态生成（当前请求，urlencode 全量编码）
        expected_redirect = urllib.parse.quote(
            "http://testserver" + CALLBACK_URL, safe=""
        )
        assert f"redirect_uri={expected_redirect}" in url
        # state 已落 Redis（含 code_verifier，供回调消费）
        stored = fake_redis.get(f"{OAuth2Service.KEY_PREFIX}:{data['state']}")
        assert stored["provider"] == "github"
        assert len(stored["code_verifier"]) == 43  # S256 兼容长度

    def test_redirect_uri_from_table(self, client, provider, fake_redis):
        provider.redirect_uri = "https://app.example.com/oauth/github/cb"
        provider.save()
        resp = client.get(AUTH_URL)
        url = resp.json()["data"]["authorize_url"]
        assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Foauth%2Fgithub%2Fcb" in url

    def test_provider_not_found(self, client):
        resp = client.get("/api/v1/users/oauth/google/authorize/")
        assert resp.status_code == 404
        assert resp.json()["errors"]["error_code"] == "provider_not_found"

    def test_inactive_provider(self, client, provider, fake_redis):
        provider.is_active = False
        provider.save()
        resp = client.get(AUTH_URL)
        assert resp.status_code == 404
        assert resp.json()["errors"]["error_code"] == "provider_not_found"

    def test_redis_unavailable(self, client, provider, monkeypatch):
        monkeypatch.setattr(OAuth2Service, "_redis_ready", lambda: False)
        resp = client.get(AUTH_URL)
        assert resp.status_code == 503
        assert resp.json()["errors"]["error_code"] == "redis_unavailable"

    def test_pkce_disabled_provider(self, client, provider, fake_redis):
        provider.pkce_enabled = False
        provider.save()
        resp = client.get(AUTH_URL)
        url = resp.json()["data"]["authorize_url"]
        assert "code_challenge" not in url
        assert "code_challenge_method" not in url


@pytest.mark.django_db
class TestOAuth2Callback:
    """授权回调：换 token → userinfo → 匹配/建号 → 签发 JWT"""

    def _authorize(self, client, fake_redis):
        """走 authorize 拿到真实 state（code_verifier 已落 Redis）"""
        resp = client.get(AUTH_URL)
        return resp.json()["data"]["state"]

    def _callback(self, client, state, code="auth_code_1", provider="github"):
        return client.get(f"/api/v1/users/oauth/{provider}/callback/",
                          {"code": code, "state": state})

    def test_auto_create_user_and_issue_jwt(self, client, provider, fake_redis, mock_http):
        mock_http()
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state)
        assert resp.status_code == 200, resp.content
        data = resp.json()["data"]
        assert data["access"] and data["refresh"]
        assert data["is_new_user"] is True
        assert data["user"]["username"] == "octocat"
        # 自动建号 + 绑定关系
        user = User.objects.get(username="octocat")
        assert user.email == "octocat@example.com"
        assert OAuthAccount.objects.filter(
            provider=provider, provider_uid="123456", user=user
        ).exists()
        # token_version 自增 + 会话 + 登录日志
        assert user.token_version >= 1
        assert UserSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1
        # access 真实可调受保护接口
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        info = api.get("/api/v1/users/info/")
        assert info.status_code == 200, info.content

    def test_email_match_existing_user_binds(self, client, provider, fake_redis, mock_http):
        mock_http()
        existing = UserFactory(email="octocat@example.com")
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state)
        assert resp.status_code == 200, resp.content
        data = resp.json()["data"]
        assert data["is_new_user"] is False
        assert data["user"]["id"] == existing.pk
        # 绑定关系落到既有用户
        assert OAuthAccount.objects.filter(provider=provider, user=existing).count() == 1

    def test_username_conflict_appends_index(self, client, provider, fake_redis, mock_http):
        mock_http()
        UserFactory(username="octocat")
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state)
        assert resp.status_code == 200, resp.content
        assert resp.json()["data"]["user"]["username"] == "octocat1"

    def test_state_single_use(self, client, provider, fake_redis, mock_http):
        mock_http()
        state = self._authorize(client, fake_redis)
        assert self._callback(client, state).status_code == 200
        # 同一 state 二次使用 → 已消费 400
        resp = self._callback(client, state)
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "invalid_state"

    def test_state_expired(self, client, provider, fake_redis, mock_http):
        resp = self._callback(client, "nonexistent-state")
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "invalid_state"

    def test_state_provider_mismatch(self, client, provider, fake_redis, mock_http):
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state, provider="github")
        # 用另一个 provider 的 state 消费：构造一个属于 google 的 state
        resp2 = client.get("/api/v1/users/oauth/google/authorize/")
        assert resp2.status_code == 404  # google 未配置
        # 直接注入 provider 不匹配的 state
        fake_redis.set(
            f"{OAuth2Service.KEY_PREFIX}:mismatch",
            {"provider": "google", "code_verifier": "x" * 43},
        )
        resp = self._callback(client, "mismatch")
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "state_provider_mismatch"

    def test_missing_code(self, client, provider, fake_redis):
        state = self._authorize(client, fake_redis)
        resp = client.get(CALLBACK_URL, {"state": state})
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "missing_code"

    def test_missing_state(self, client, provider, fake_redis):
        resp = client.get(CALLBACK_URL, {"code": "x"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "missing_state"

    def test_provider_denied(self, client):
        resp = client.get(CALLBACK_URL, {"error": "access_denied"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "provider_denied"

    def test_token_exchange_failure(self, client, provider, fake_redis, mock_http):
        mock_http(token_error=OAuth2Error(
            "第三方授权服务返回错误", 502, "provider_http_error"))
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state)
        assert resp.status_code == 502
        assert resp.json()["errors"]["error_code"] == "provider_http_error"

    def test_userinfo_missing_uid(self, client, provider, fake_redis, mock_http):
        mock_http(profile={"login": "no-id"})
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state)
        assert resp.status_code == 502
        assert resp.json()["errors"]["error_code"] == "invalid_userinfo"

    def test_auto_bind_email_disabled(self, client, provider, fake_redis, mock_http):
        mock_http()
        existing = UserFactory(email="octocat@example.com")
        # 关闭 email 绑定 + 关闭自动建号 → 既有邮箱账号不被接管 → unbound 400
        with override_settings(OAUTH2_AUTO_BIND_EMAIL=False, OAUTH2_AUTO_CREATE_USER=False):
            state = self._authorize(client, fake_redis)
            resp = self._callback(client, state)
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "unbound_account"
        # 未产生任何绑定关系
        assert OAuthAccount.objects.filter(provider=provider).count() == 0

    def test_auto_create_user_disabled(self, client, provider, fake_redis, mock_http):
        mock_http()
        with override_settings(OAUTH2_AUTO_CREATE_USER=False):
            state = self._authorize(client, fake_redis)
            resp = self._callback(client, state)
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "unbound_account"

    def test_redirect_to_frontend(self, client, provider, fake_redis, mock_http):
        mock_http()
        with override_settings(OAUTH2_FRONTEND_REDIRECT_URL="https://app.example.com/oauth-cb"):
            state = self._authorize(client, fake_redis)
            resp = self._callback(client, state)
        assert resp.status_code == 302
        assert resp.url.startswith("https://app.example.com/oauth-cb?")
        assert "access=" in resp.url
        assert "refresh=" in resp.url

    def test_sub_fallback_when_no_id(self, client, provider, fake_redis, mock_http):
        mock_http(profile={"sub": "google-sub-xyz", "email": "g@example.com"})
        state = self._authorize(client, fake_redis)
        resp = self._callback(client, state)
        assert resp.status_code == 200, resp.content
        assert resp.json()["data"]["user"]["username"] == "g"
        assert OAuthAccount.objects.filter(provider_uid="google-sub-xyz").exists()


@pytest.mark.django_db
class TestOAuth2Bind:
    """已登录用户绑定第三方账号"""

    def _authorize(self, client, fake_redis):
        resp = client.get(AUTH_URL)
        return resp.json()["data"]["state"]

    def test_bind_success(self, client, provider, fake_redis, mock_http):
        mock_http()
        user = UserFactory()
        client.force_authenticate(user=user)
        state = self._authorize(client, fake_redis)
        resp = client.post(BIND_URL, {"code": "auth_code_1", "state": state}, format="json")
        assert resp.status_code == 200, resp.content
        data = resp.json()["data"]
        assert data["bound"] is True
        assert data["created"] is True
        assert OAuthAccount.objects.filter(provider=provider, user=user).count() == 1
        # 用户 token_version 未被自增（绑定不是登录）
        assert user.token_version == 0

    def test_bind_already_bound_to_other(self, client, provider, fake_redis, mock_http):
        mock_http()
        user = UserFactory()
        other = UserFactory()
        OAuthAccount.objects.create(
            user=other, provider=provider, provider_uid="123456"
        )
        client.force_authenticate(user=user)
        state = self._authorize(client, fake_redis)
        resp = client.post(BIND_URL, {"code": "auth_code_1", "state": state}, format="json")
        assert resp.status_code == 409
        assert resp.json()["errors"]["error_code"] == "account_already_bound"

    def test_bind_requires_auth(self, client, provider, fake_redis, mock_http):
        state = self._authorize(client, fake_redis)
        resp = client.post(BIND_URL, {"code": "x", "state": state}, format="json")
        assert resp.status_code == 401
