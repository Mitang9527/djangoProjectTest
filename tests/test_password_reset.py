"""找回密码（邮箱重置）—— 防枚举 + IP/email 限流 + 一次性 token 全链路。

覆盖：
  1. 请求：发邮件（含 token / uid 或前端链接）、用户不存在响应一致且不发邮件（防枚举）；
  2. 限流：IP / email 双维度计数，达阈值 429（注入内存 FakeRedis）；
  3. 确认：合法 token 重置成功 → 旧密码失效 / 新密码可登录 / 全部会话吊销 /
     token_version 自增 / PASSWORD_CHANGE 审计；
  4. 异常：uid 非法、token 无效 / 复用、弱密码均 400。
"""
from unittest import mock

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from framework.gateway.login_throttle import LoginThrottleService
from system.core.models import AuditLog
from system.users.models import User, UserSession


class _FakeRedis:
    """内存版 RedisClient（仅实现重置限流用到的命令）"""

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


def _patch_redis(fake):
    return mock.patch.object(LoginThrottleService, "_client", new=lambda: fake)


class PasswordResetBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resetuser", password="Pass123!", email="reset@v.com"
        )
        self.request_url = "/api/v1/users/password/reset/request/"
        self.confirm_url = "/api/v1/users/password/reset/confirm/"
        self.login_url = "/api/v1/users/jwt/login/"

    def _request_reset(self, payload, **headers):
        return APIClient().post(self.request_url, payload, format="json", **headers)

    def _confirm(self, user, new_password="NewPass#2026", token=None, uid=None):
        # 生成 token 前取最新 user：登录等操作会更新 last_login（token 哈希输入），
        # 内存旧对象会与视图侧 DB 重载对象哈希不一致 → 模拟生产（request 视图生成 token）
        user = User.objects.get(pk=user.pk)
        token = token or default_token_generator.make_token(user)
        uid = uid or urlsafe_base64_encode(force_bytes(user.pk))
        return APIClient().post(
            self.confirm_url,
            {"uid": uid, "token": token, "new_password": new_password},
            format="json",
        )

    def _login(self, password="Pass123!"):
        resp = APIClient().post(
            self.login_url,
            {"username": "resetuser", "password": password},
            format="json",
        )
        return resp.status_code


class PasswordResetRequestTest(PasswordResetBase):
    def test_request_sends_email_with_credentials(self):
        resp = self._request_reset({"email": "reset@v.com"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["reset@v.com"])
        self.assertIn("重置", msg.subject)
        # FRONTEND_URL 未配置 → 邮件内含 uid + token 明文凭证
        self.assertIn("uid:", msg.body)
        self.assertIn("token:", msg.body)

    @override_settings(PASSWORD_RESET_FRONTEND_URL="https://app.example.com/reset-password")
    def test_request_sends_link_when_frontend_configured(self):
        self._request_reset({"email": "reset@v.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://app.example.com/reset-password?uid=", mail.outbox[0].body)

    def test_unknown_email_identical_response_no_email(self):
        known = self._request_reset({"email": "reset@v.com"})
        mail.outbox.clear()
        unknown = self._request_reset({"email": "nobody@v.com"})
        # 响应完全一致（防枚举），且未知邮箱不发邮件
        self.assertEqual(known.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(
            known.json()["data"]["message"], unknown.json()["data"]["message"]
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_request_requires_email_or_username(self):
        resp = self._request_reset({})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_request_username_works(self):
        resp = self._request_reset({"username": "resetuser"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reset@v.com"])

    @override_settings(
        PASSWORD_RESET_RATE_LIMIT_MAX_ATTEMPTS=2,
        PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS=3600,
        PASSWORD_RESET_RATE_LIMIT_BLOCK_SECONDS=3600,
    )
    def test_request_rate_limited_per_ip(self):
        fake = _FakeRedis()
        with _patch_redis(fake):
            self.assertEqual(self._request_reset({"email": "reset@v.com"}).status_code, 200)
            self.assertEqual(self._request_reset({"email": "reset@v.com"}).status_code, 200)
            # 第三次达阈值 → 429（成功也计数，防批量轰炸）
            resp = self._request_reset({"email": "reset@v.com"})
            self.assertEqual(resp.status_code, 429, resp.content)

    @override_settings(
        PASSWORD_RESET_RATE_LIMIT_MAX_ATTEMPTS=2,
        PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS=3600,
        PASSWORD_RESET_RATE_LIMIT_BLOCK_SECONDS=3600,
    )
    def test_request_rate_limited_per_email(self):
        fake = _FakeRedis()
        with _patch_redis(fake):
            self.assertEqual(self._request_reset(
                {"email": "reset@v.com"}, HTTP_X_FORWARDED_FOR="1.1.1.1").status_code, 200)
            self.assertEqual(self._request_reset(
                {"email": "reset@v.com"}, HTTP_X_FORWARDED_FOR="2.2.2.2").status_code, 200)
            # 换 IP 但同一 email 仍被 email 维度拦截
            resp = self._request_reset(
                {"email": "reset@v.com"}, HTTP_X_FORWARDED_FOR="3.3.3.3")
            self.assertEqual(resp.status_code, 429, resp.content)


class PasswordResetConfirmTest(PasswordResetBase):
    def test_confirm_resets_password_and_kills_sessions(self):
        # 先登录建会话（版本戳 +1）
        self.assertEqual(self._login(), 200)
        version_before = User.objects.get(pk=self.user.pk).token_version
        session_count = UserSession.objects.filter(
            user=self.user, revoked_at__isnull=True
        ).count()
        self.assertEqual(session_count, 1)

        resp = self._confirm(self.user)
        self.assertEqual(resp.status_code, 200, resp.content)

        # token_version 自增 + 全部旧会话吊销（在再次登录前断言）
        self.assertGreater(
            User.objects.get(pk=self.user.pk).token_version, version_before
        )
        self.assertEqual(
            UserSession.objects.filter(user=self.user, revoked_at__isnull=True).count(), 0
        )
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.user, action="PASSWORD_CHANGE", log_type="SENSITIVE",
            ).exists()
        )

        # 旧密码失效、新密码可登录（新登录会重建会话，故上述断言须在登录前）
        self.assertEqual(self._login("Pass123!"), 401)
        self.assertEqual(self._login("NewPass#2026"), 200)

    def test_confirm_invalid_token(self):
        resp = self._confirm(self.user, token="bad-token-123")
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_confirm_invalid_uid(self):
        resp = self._confirm(self.user, uid="bm90LWEtdXNlcg==")  # 非用户
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_confirm_weak_password(self):
        resp = self._confirm(self.user, new_password="abc123")
        self.assertEqual(resp.status_code, 400, resp.content)
        # 密码未被修改
        self.assertEqual(self._login(), 200)

    def test_confirm_token_single_use(self):
        token = default_token_generator.make_token(self.user)
        self.assertEqual(self._confirm(self.user, token=token).status_code, 200)
        # 改密后 token 失效（哈希变更），复用直接 400
        resp = self._confirm(self.user, token=token)
        self.assertEqual(resp.status_code, 400, resp.content)
