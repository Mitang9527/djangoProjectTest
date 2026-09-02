"""MFA TOTP + 恢复码端到端验证（对齐 Fast-Vben-Admin core/mfa.py）。

覆盖：
- 工具层：TOTP 生成/校验/归一化、Fernet 加密往返、错误密钥解密失败；
- 服务层：setup(pending) → confirm(启用) → disable / regenerate 恢复码；
- 登录链：四个入口（UserLoginView / LoginService / TokenService /
  CustomTokenObtainPairSerializer）的 mfa_required / mfa_failed 语义，
  以及「恢复码一次性消费」「MFA 失败计入登录限流」。

说明：登录限流相关断言复用 _FakeRedis 注入（同 test_login_throttle.py）。
"""
from unittest import mock

import pyotp

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from system.users.models import User
from system.users.services import LoginService, TokenService, MfaService
from framework.gateway.login_throttle import LoginThrottleService
from framework.security import mfa as mfa_tools


class _FakeRedis:
    """内存版 RedisClient（仅实现登录限流用到的命令）"""

    def __init__(self):
        self._data = {}

    def incr(self, key, amount=1):
        value = int(self._data.get(key, 0)) + amount
        self._data[key] = value
        return value

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ex=None, **kwargs):
        self._data[key] = value
        return True

    def delete(self, *keys):
        n = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                n += 1
        return n

    def expire(self, key, time):
        return True

    def exists(self, key):
        return key in self._data


def _patch_redis(fake):
    return mock.patch.object(LoginThrottleService, "_client", new=lambda: fake)


def _current_totp(secret: str) -> str:
    return pyotp.TOTP(secret).now()


# ──────────────────────────────────────────────
# 工具层
# ──────────────────────────────────────────────

class MfaToolsTest(TestCase):
    def test_totp_accepts_current_code(self):
        secret = mfa_tools.generate_totp_secret()
        code = _current_totp(secret)
        self.assertTrue(mfa_tools.verify_totp_code(secret=secret, code=code))

    def test_totp_rejects_wrong_code(self):
        secret = mfa_tools.generate_totp_secret()
        self.assertFalse(mfa_tools.verify_totp_code(secret=secret, code="000000"))
        self.assertFalse(mfa_tools.verify_totp_code(secret=secret, code=""))
        self.assertFalse(mfa_tools.verify_totp_code(secret=secret, code="abc"))

    def test_totp_normalize_strips_non_digits(self):
        self.assertEqual(mfa_tools.normalize_totp_code(" 123-456 "), "123456")
        self.assertEqual(mfa_tools.normalize_totp_code(""), "")

    def test_encrypt_decrypt_roundtrip(self):
        secret = mfa_tools.generate_totp_secret()
        enc = mfa_tools.encrypt_secret(secret)
        self.assertEqual(mfa_tools.decrypt_secret(enc), secret)

    def test_decrypt_wrong_key_raises(self):
        # 不同 SECRET_KEY 派生不同 Fernet key → 解密失败抛 ValueError
        enc = mfa_tools.encrypt_secret("ABCDEFGH")
        with override_settings(SECRET_KEY="another-secret-key-for-test-1234567890"):
            with self.assertRaises(ValueError):
                mfa_tools.decrypt_secret(enc)

    def test_recovery_code_consume_once(self):
        codes = mfa_tools.generate_recovery_codes(count=3)
        serialized = mfa_tools.serialize_recovery_codes(codes)
        self.assertEqual(mfa_tools.get_recovery_code_count(serialized), 3)

        remaining = mfa_tools.consume_recovery_code(serialized, codes[0])
        self.assertIsNotNone(remaining)
        self.assertEqual(mfa_tools.get_recovery_code_count(remaining), 2)
        # 同码二次消费 → None（一次性）
        self.assertIsNone(mfa_tools.consume_recovery_code(remaining, codes[0]))
        # 未命中码 → None 且数量不变
        self.assertIsNone(mfa_tools.consume_recovery_code(remaining, "NOT-A-CODE"))
        self.assertEqual(mfa_tools.get_recovery_code_count(remaining), 2)


# ──────────────────────────────────────────────
# 服务层：绑定 / 启用 / 禁用 / 恢复码
# ──────────────────────────────────────────────

class MfaServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mfa_user", password="Pass123!", email="mfa@v.com")

    def _setup_and_confirm(self):
        """完成绑定流程，返回 (secret, recovery_codes)。"""
        result = MfaService.setup(self.user)
        secret = result["secret"]
        codes = result["recovery_codes"]
        MfaService.confirm(self.user, _current_totp(secret))
        return secret, codes

    def test_setup_creates_pending_binding(self):
        result = MfaService.setup(self.user)
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)  # pending，未启用
        self.assertIsNotNone(self.user.mfa_secret_encrypted)
        self.assertIsNone(self.user.mfa_confirmed_at)
        self.assertEqual(len(result["recovery_codes"]), 10)
        self.assertIn("secret", result)
        # otpauth URI：issuer 与 secret 参数齐备（issuer 标签为 URL 编码形式）
        self.assertIn("otpauth://", result["uri"])
        self.assertIn("issuer=", result["uri"])
        self.assertIn("secret=", result["uri"])

    def test_confirm_enables_mfa(self):
        secret, _ = self._setup_and_confirm()
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)
        self.assertIsNotNone(self.user.mfa_confirmed_at)
        # 启用后校验原 secret 仍可解密（落库值一致）
        self.assertEqual(mfa_tools.decrypt_secret(self.user.mfa_secret_encrypted), secret)

    def test_confirm_wrong_code_raises(self):
        from rest_framework.exceptions import ValidationError
        MfaService.setup(self.user)
        with self.assertRaises(ValidationError):
            MfaService.confirm(self.user, "000000")

    def test_confirm_without_setup_raises(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            MfaService.confirm(self.user, "123456")

    def test_setup_when_enabled_requires_current_mfa(self):
        from rest_framework.exceptions import ValidationError
        secret, _ = self._setup_and_confirm()
        # 已启用后 setup 不带验证 → 拒绝（防劫持换绑）
        with self.assertRaises(ValidationError):
            MfaService.setup(self.user)
        # 带当前 TOTP → 允许换绑（新 secret pending，旧 MFA 未确认不生效）
        new_result = MfaService.setup(self.user, mfa_code=_current_totp(secret))
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)  # 换绑后回到 pending
        self.assertNotEqual(new_result["secret"], secret)

    def test_disable_with_totp(self):
        secret, _ = self._setup_and_confirm()
        result = MfaService.disable(self.user, _current_totp(secret))
        self.user.refresh_from_db()
        self.assertFalse(result["mfa_enabled"])
        self.assertIsNone(self.user.mfa_secret_encrypted)
        self.assertIsNone(self.user.mfa_recovery_code_hashes)

    def test_disable_with_recovery_code(self):
        _, codes = self._setup_and_confirm()
        MfaService.disable(self.user, codes[0])
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)

    def test_regenerate_recovery_codes(self):
        secret, old_codes = self._setup_and_confirm()
        result = MfaService.regenerate_recovery_codes(self.user, _current_totp(secret))
        new_codes = result["recovery_codes"]
        self.assertEqual(len(new_codes), 10)
        self.user.refresh_from_db()
        # 新码可消费、旧码已作废
        self.assertIsNotNone(
            mfa_tools.consume_recovery_code(self.user.mfa_recovery_code_hashes, new_codes[0]))
        self.assertIsNone(
            mfa_tools.consume_recovery_code(self.user.mfa_recovery_code_hashes, old_codes[0]))


# ──────────────────────────────────────────────
# 登录链：mfa_required / mfa_failed / 恢复码 / 限流
# ──────────────────────────────────────────────

class MfaLoginTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mfa_login", password="Pass123!", email="ml@v.com")
        self.login_url = "/api/v1/users/login/"
        self.jwt_login_url = "/api/v1/users/jwt/login/"

    def _enable_mfa(self):
        """启用 MFA，返回 (secret, recovery_codes)。"""
        result = MfaService.setup(self.user)
        MfaService.confirm(self.user, _current_totp(result["secret"]))
        self.user.refresh_from_db()
        return result["secret"], result["recovery_codes"]

    def _post_login(self, url, mfa_code=None, password="Pass123!"):
        c = APIClient()
        data = {"username": "mfa_login", "password": password}
        if mfa_code is not None:
            data["mfa_code"] = mfa_code
        return c.post(url, data, format="json")

    # ── 主登录视图（/api/v1/users/login/） ──────────

    def test_login_requires_mfa_code(self):
        self._enable_mfa()
        resp = self._post_login(self.login_url)
        self.assertEqual(resp.status_code, 400, resp.content)
        # CustomRenderer：detail+code 落入 errors.error_code
        self.assertEqual(resp.json()["errors"]["error_code"], "mfa_required")

    def test_login_with_totp_succeeds(self):
        secret, _ = self._enable_mfa()
        resp = self._post_login(self.login_url, mfa_code=_current_totp(secret))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("access", resp.json()["data"])

    def test_login_with_recovery_code_succeeds_once(self):
        _, codes = self._enable_mfa()
        resp = self._post_login(self.login_url, mfa_code=codes[0])
        self.assertEqual(resp.status_code, 200, resp.content)
        # 同一恢复码二次登录 → 一次性失效，返回二次验证失败
        resp2 = self._post_login(self.login_url, mfa_code=codes[0])
        self.assertEqual(resp2.status_code, 401, resp2.content)
        self.assertEqual(resp2.json()["errors"]["error_code"], "mfa_failed")

    def test_login_wrong_mfa_code_fails(self):
        self._enable_mfa()
        resp = self._post_login(self.login_url, mfa_code="000000")
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_mfa_failed_counts_login_throttle(self):
        """MFA 失败计入登录限流：5 次失败后即使 MFA 正确也被 429 拦截。"""
        fake = _FakeRedis()
        self._enable_mfa()
        with _patch_redis(fake):
            for _ in range(5):
                resp = self._post_login(self.login_url, mfa_code="000000")
                self.assertEqual(resp.status_code, 401, resp.content)
            # 第 6 次 MFA 正确 → 仍被 IP 维度锁定拦截
            resp = self._post_login(self.login_url, mfa_code=_current_totp(
                mfa_tools.decrypt_secret(self.user.mfa_secret_encrypted)))
        self.assertEqual(resp.status_code, 429, resp.content)

    # ── 标准 JWT 登录（/api/v1/users/jwt/login/） ────

    def test_jwt_login_requires_mfa_code(self):
        self._enable_mfa()
        resp = self._post_login(self.jwt_login_url)
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.json()["errors"]["error_code"], "mfa_required")

    def test_jwt_login_with_totp_succeeds(self):
        secret, _ = self._enable_mfa()
        resp = self._post_login(self.jwt_login_url, mfa_code=_current_totp(secret))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("access", resp.json()["data"])

    # ── 服务层（request=None，与 test_token_version 调用形态一致） ──

    def test_login_service_mfa_required(self):
        self._enable_mfa()
        res = LoginService.login(username="mfa_login", password="Pass123!")
        self.assertEqual(res.get("error"), "mfa_required")

    def test_login_service_with_totp_succeeds(self):
        secret, _ = self._enable_mfa()
        res = LoginService.login(
            username="mfa_login", password="Pass123!",
            mfa_code=_current_totp(secret))
        self.assertIn("tokens", res)

    def test_token_service_mfa_required(self):
        self._enable_mfa()
        res = TokenService.jwt_login(username="mfa_login", password="Pass123!")
        self.assertEqual(res.get("error"), "mfa_required")

    def test_no_mfa_login_unaffected(self):
        # 未启用 MFA 的用户登录不要求 mfa_code
        resp = self._post_login(self.login_url)
        self.assertEqual(resp.status_code, 200, resp.content)


# ──────────────────────────────────────────────
# MFA 管理端点（认证）
# ──────────────────────────────────────────────

class MfaApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mfa_api", password="Pass123!", email="ma@v.com")
        self.client = APIClient()

    def _auth_client(self):
        self.client.force_authenticate(user=self.user)
        return self.client

    def test_status_requires_auth(self):
        resp = self.client.get("/api/v1/users/mfa/status/")
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_status_initial(self):
        resp = self._auth_client().get("/api/v1/users/mfa/status/")
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()["data"] if "data" in resp.json() else resp.json()
        self.assertFalse(body["mfa_enabled"])
        self.assertEqual(body["recovery_codes_remaining"], 0)

    def test_full_flow_setup_confirm_login_disable(self):
        c = self._auth_client()

        # 1. setup → 返回 secret + 恢复码
        resp = c.post("/api/v1/users/mfa/setup/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()["data"] if "data" in resp.json() else resp.json()
        secret = body["secret"]
        codes = body["recovery_codes"]
        self.assertEqual(len(codes), 10)

        # 2. confirm 错误码 → 400
        resp = c.post("/api/v1/users/mfa/confirm/", {"code": "000000"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)

        # 3. confirm 正确码 → 启用
        resp = c.post("/api/v1/users/mfa/confirm/",
                      {"code": _current_totp(secret)}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)

        # 4. status → 已启用，恢复码 10 个
        resp = c.get("/api/v1/users/mfa/status/")
        body = resp.json()["data"] if "data" in resp.json() else resp.json()
        self.assertTrue(body["mfa_enabled"])
        self.assertEqual(body["recovery_codes_remaining"], 10)

        # 5. 登录须携带 mfa_code
        login = APIClient().post(
            "/api/v1/users/login/",
            {"username": "mfa_api", "password": "Pass123!"}, format="json")
        self.assertEqual(login.status_code, 400, login.content)

        # 6. disable 用恢复码 → 禁用后登录不再要求二次验证
        resp = c.post("/api/v1/users/mfa/disable/", {"code": codes[0]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)
        login2 = APIClient().post(
            "/api/v1/users/login/",
            {"username": "mfa_api", "password": "Pass123!"}, format="json")
        self.assertEqual(login2.status_code, 200, login2.content)

    def test_recovery_regenerate_endpoint(self):
        c = self._auth_client()
        resp = c.post("/api/v1/users/mfa/setup/", {}, format="json")
        secret = resp.json()["data"]["secret"]
        c.post("/api/v1/users/mfa/confirm/", {"code": _current_totp(secret)}, format="json")

        resp = c.post("/api/v1/users/mfa/recovery/", {"code": _current_totp(secret)},
                      format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        new_codes = resp.json()["data"]["recovery_codes"]
        self.assertEqual(len(new_codes), 10)

        # 错误 TOTP → 400
        resp = c.post("/api/v1/users/mfa/recovery/", {"code": "000000"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
