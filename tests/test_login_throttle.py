"""登录双维度限流（IP + 用户名）端到端验证。

语义对齐 Fast-Vben-Admin ``login.py``：
- 失败计数：IP / 用户名两个维度分别 INCR + 窗口 TTL；
- 锁定：任一维度窗口内失败次数 >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS 即锁定该维度
  LOGIN_RATE_LIMIT_BLOCK_SECONDS 秒（block key），期间对应登录直接 429；
- 解锁：登录成功后清零两个维度；
- 故障：Redis 不可用 / 配置禁用时 fail-open 放行（登录可用性优先）。

说明：测试环境 Redis 通常不可达（_NullRedis 的 incr 恒返回 1，计数无法累积），
因此通过 mock ``LoginThrottleService._client`` 注入内存版 FakeRedis 来验证
计数 / 锁定 / 清零语义。成功 / 失败行为均走真实 URL（/api/v1/users/login/ 等）。
"""
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from system.users.models import User
from system.users.services import LoginService
from framework.gateway.login_throttle import LoginThrottleService


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
    """把 LoginThrottleService 的 Redis 客户端替换为内存 FakeRedis。"""
    return mock.patch.object(LoginThrottleService, "_client", new=lambda: fake)


class LoginThrottleAPITest(TestCase):
    """API 层：真实 URL + 注入 FakeRedis"""

    def setUp(self):
        self.fake = _FakeRedis()
        self.user = User.objects.create_user(
            username="throttle_user", password="Pass123!", email="thr@v.com")
        self.login_url = "/api/v1/users/login/"
        self.jwt_login_url = "/api/v1/users/jwt/login/"

    def _post(self, url, username, password, ip=None):
        c = APIClient()
        kwargs = {}
        if ip:
            kwargs["HTTP_X_FORWARDED_FOR"] = ip
        return c.post(url, {"username": username, "password": password},
                      format="json", **kwargs)

    # ── 主登录入口（/api/v1/users/login/） ─────────────────

    def test_max_failed_attempts_blocks_even_with_correct_password(self):
        with _patch_redis(self.fake):
            for _ in range(5):
                resp = self._post(self.login_url, "throttle_user", "wrong-pass")
                self.assertEqual(resp.status_code, 401, resp.content)
            # 第 6 次密码正确 → 仍 429（IP 维度已锁定）
            resp = self._post(self.login_url, "throttle_user", "Pass123!")
        self.assertEqual(resp.status_code, 429, resp.content)

    def test_successful_login_clears_attempts(self):
        with _patch_redis(self.fake):
            # 未达上限的失败 + 成功 → 计数清零
            for _ in range(4):
                self._post(self.login_url, "throttle_user", "wrong-pass")
            resp = self._post(self.login_url, "throttle_user", "Pass123!")
            self.assertEqual(resp.status_code, 200, resp.content)
            # 成功瞬间计数已清零（IP / 用户名维度均无残留）
            self.assertFalse(
                [k for k in self.fake._data if k.startswith("ratelimit:login:")],
                self.fake._data,
            )
            # 清零后重新计数：再错 5 次（第 5 次触发锁定返回 401）
            for _ in range(4):
                self._post(self.login_url, "throttle_user", "wrong-pass")
            resp2 = self._post(self.login_url, "throttle_user", "wrong-pass")
            self.assertEqual(resp2.status_code, 401, resp2.content)

    def test_user_dimension_locks_across_ips(self):
        with _patch_redis(self.fake):
            for i in range(3):
                self._post(self.login_url, "throttle_user", "wrong-pass", ip=f"1.0.0.{i}")
            for i in range(2):
                self._post(self.login_url, "throttle_user", "wrong-pass", ip=f"2.0.0.{i}")
            # 用户名维度累计 5 次 → 锁定；换全新 IP 也被拦
            resp = self._post(self.login_url, "throttle_user", "Pass123!", ip="9.9.9.9")
        self.assertEqual(resp.status_code, 429, resp.content)

    # ── 标准 JWT 登录入口（/api/v1/users/jwt/login/） ──────

    def test_jwt_login_view_throttled(self):
        with _patch_redis(self.fake):
            for _ in range(5):
                resp = self._post(self.jwt_login_url, "throttle_user", "wrong-pass")
                self.assertEqual(resp.status_code, 401, resp.content)
            resp = self._post(self.jwt_login_url, "throttle_user", "Pass123!")
        self.assertEqual(resp.status_code, 429, resp.content)

    # ── 服务层（request=None 场景，与 test_token_version 调用形态一致） ──

    def test_login_service_rate_limited(self):
        with _patch_redis(self.fake):
            for _ in range(5):
                LoginThrottleService.record_failed_login_attempt(None, "throttle_user")
            res = LoginService.login(username="throttle_user", password="Pass123!")
        self.assertEqual(res.get("error"), "rate_limited")

    # ── 故障 / 禁用降级（fail-open） ──────────────────────

    def test_redis_unavailable_fail_open(self):
        # Redis 客户端为 None（不可用）→ 无限失败也不锁定，登录照常
        with mock.patch.object(LoginThrottleService, "_client", new=lambda: None):
            for _ in range(10):
                self._post(self.login_url, "throttle_user", "wrong-pass")
            resp = self._post(self.login_url, "throttle_user", "Pass123!")
        self.assertEqual(resp.status_code, 200, resp.content)

    @override_settings(LOGIN_RATE_LIMIT_ENABLED=False)
    def test_disabled_feature_no_throttle(self):
        with _patch_redis(self.fake):
            for _ in range(10):
                self._post(self.login_url, "throttle_user", "wrong-pass")
            resp = self._post(self.login_url, "throttle_user", "Pass123!")
        self.assertEqual(resp.status_code, 200, resp.content)


@override_settings(ALLOW_DEMO_LOGIN=True)
class DemoLoginThrottleTest(TestCase):
    """演示登录入口（/api/v1/core/demo-login/）同样受限流保护"""

    def setUp(self):
        self.fake = _FakeRedis()

    def test_demo_login_throttled(self):
        with _patch_redis(self.fake):
            # 用户名维度预置 5 次失败 → 锁定
            for _ in range(5):
                LoginThrottleService.record_failed_login_attempt(None, "demo_user")
            c = APIClient()
            resp = c.post("/api/v1/core/demo-login/", {"username": "demo_user"},
                          format="json")
        self.assertEqual(resp.status_code, 429, resp.content)

    def test_demo_login_success_clears_attempts(self):
        from rest_framework.test import APIRequestFactory

        with _patch_redis(self.fake):
            # 用带真实 IP 的请求预置失败计数（与后续 APIClient 请求同一 IP 维度）
            factory = APIRequestFactory()
            for _ in range(4):
                req = factory.post("/api/v1/core/demo-login/",
                                   {"username": "demo_user"}, format="json")
                LoginThrottleService.record_failed_login_attempt(req, "demo_user")
            c = APIClient()
            resp = c.post("/api/v1/core/demo-login/", {"username": "demo_user"},
                          format="json")
            self.assertEqual(resp.status_code, 200, resp.content)
            # 成功清零 IP / 用户名双维度
            self.assertFalse(
                [k for k in self.fake._data if k.startswith("ratelimit:login:")],
                self.fake._data,
            )


class RegisterThrottleTest(TestCase):
    """注册入口（/api/v1/users/register/）IP 维度防批量刷注册"""

    def setUp(self):
        self.fake = _FakeRedis()
        self.register_url = "/api/v1/users/register/"

    def _register(self, username, ip=None):
        c = APIClient()
        kwargs = {}
        if ip:
            kwargs["HTTP_X_FORWARDED_FOR"] = ip
        return c.post(self.register_url, {
            "username": username,
            "password": "Pass123!",
            "password_confirm": "Pass123!",
            "email": f"{username}@example.com",
        }, format="json", **kwargs)

    def _register_invalid(self, ip):
        """构造校验失败（密码过短 + 非法邮箱）的注册请求。"""
        c = APIClient()
        return c.post(self.register_url, {
            "username": "bad_user",
            "password": "short",
            "password_confirm": "short",
            "email": "not-an-email",
        }, format="json", **{"HTTP_X_FORWARDED_FOR": ip})

    def test_register_max_attempts_blocks_ip(self):
        with _patch_redis(self.fake):
            for i in range(10):
                resp = self._register(f"user{i}", ip="5.5.5.5")
                self.assertEqual(resp.status_code, 201, resp.content)
            # 第 11 次（IP 已锁定）→ 429
            resp = self._register("user10", ip="5.5.5.5")
        self.assertEqual(resp.status_code, 429, resp.content)

    def test_register_success_counts_toward_limit(self):
        # 防批量刷注册：成功注册同样消耗窗口额度（不清零），窗口内注册数受控
        with _patch_redis(self.fake):
            for i in range(9):
                resp = self._register(f"ok{i}", ip="6.6.6.6")
                self.assertEqual(resp.status_code, 201, resp.content)
            # 第 10 次成功注册：请求本身通过，但记录后触发 IP 锁定
            resp = self._register("tenth", ip="6.6.6.6")
            self.assertEqual(resp.status_code, 201, resp.content)
            # 第 11 次（数据有效）→ 429（窗口内已达 10 次）
            resp2 = self._register("eleventh", ip="6.6.6.6")
        self.assertEqual(resp2.status_code, 429, resp2.content)

    def test_register_invalid_data_counts(self):
        # 校验失败同样计数：10 次无效请求后，有效请求也被拦截（IP 已锁定）
        with _patch_redis(self.fake):
            for _ in range(10):
                resp = self._register_invalid(ip="9.9.9.9")
                self.assertEqual(resp.status_code, 400, resp.content)
            resp = self._register("valid_after_bad", ip="9.9.9.9")
        self.assertEqual(resp.status_code, 429, resp.content)

    def test_register_redis_unavailable_fail_open(self):
        # Redis 不可用 → 无限注册也不锁定
        with mock.patch.object(LoginThrottleService, "_client", new=lambda: None):
            resp = None
            for i in range(15):
                resp = self._register(f"fo{i}", ip="7.7.7.7")
        self.assertEqual(resp.status_code, 201, resp.content)

    @override_settings(REGISTER_RATE_LIMIT_ENABLED=False)
    def test_register_disabled_no_throttle(self):
        with _patch_redis(self.fake):
            resp = None
            for i in range(15):
                resp = self._register(f"off{i}", ip="8.8.8.8")
        self.assertEqual(resp.status_code, 201, resp.content)
