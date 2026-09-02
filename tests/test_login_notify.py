"""新设备登录站内信提醒（登录安全 best-effort 通知）。

覆盖：
  1. 首次登录 → 站内信（level=warning，含时间/IP/设备，绑租户）；
  2. 同设备（同 IP+UA）再登录 → 不重复提醒；
  3. 不同 IP 登录（模拟新设备）→ 再次提醒；
  4. 主登录（/login/）与 JWT 登录（/jwt/login/）均触发；
  5. 刷新 token / 切租户等非登录签发 → 不触发（notify_new_device=False 默认）；
  6. 模板缺失 → 回退默认文案仍发送；
  7. 发送抛异常 → 登录不受影响（best-effort 吞错）；
  8. DemoLogin 触发（ALLOW_DEMO_LOGIN=True）。
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from business.alert_system.models import InAppMessage, MessageTemplate
from system.saas.models import Role, Tenant, TenantMember
from system.users.models import User


class LoginNotifyBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="notifyuser", password="Pass123!", email="notify@v.com"
        )
        self.tenant = Tenant.objects.create(name="通知租户", slug="ntfy")
        role = Role.objects.filter(slug="member", tenant__isnull=True).first()
        TenantMember.objects.create(
            tenant=self.tenant, user=self.user, role=role,
            is_active=True, is_default=True,
        )
        self.jwt_login_url = "/api/v1/users/jwt/login/"
        self.main_login_url = "/api/v1/users/login/"
        self.refresh_url = "/api/v1/users/jwt/refresh/"
        self.demo_login_url = "/api/v1/core/demo-login/"

    def _login(self, url=None, username="notifyuser", password="Pass123!",
               xff=None, ua=None, **headers):
        c = APIClient()
        kwargs = dict(headers)
        if xff:
            kwargs["HTTP_X_FORWARDED_FOR"] = xff
        if ua:
            kwargs["HTTP_USER_AGENT"] = ua
        resp = c.post(url or self.jwt_login_url,
                      {"username": username, "password": password},
                      format="json", **kwargs)
        return resp

    def _messages(self, user=None):
        qs = InAppMessage.objects.filter(user=user or self.user)
        return list(qs.order_by("id"))


class LoginNotifyTest(LoginNotifyBase):
    def test_first_login_creates_warning_message(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 200, resp.content)
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        m = msgs[0]
        self.assertEqual(m.level, "warning")
        self.assertEqual(m.tenant_id, self.tenant.id)
        # 内容渲染了占位符
        self.assertIn("127.0.0.1", m.content)
        self.assertIn("新设备", m.title)

    def test_same_device_relogin_no_duplicate(self):
        self._login()
        self._login()  # 同 IP + 同 UA（测试客户端 UA 为空）再登录
        self.assertEqual(len(self._messages()), 1)

    def test_different_ip_triggers_again(self):
        self._login()
        self._login(xff="10.20.30.40")
        msgs = self._messages()
        self.assertEqual(len(msgs), 2)
        self.assertIn("10.20.30.40", msgs[1].content)

    def test_different_ua_triggers_again(self):
        self._login()
        self._login(ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
        msgs = self._messages()
        self.assertEqual(len(msgs), 2)
        # 设备标识从 UA 括号内提取
        self.assertIn("iPhone", msgs[1].content)

    def test_main_login_also_triggers(self):
        resp = self._login(url=self.main_login_url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(self._messages()), 1)

    def test_refresh_does_not_trigger(self):
        resp = self._login()
        data = resp.json()["data"]
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + data["access"])
        refresh_resp = c.post(self.refresh_url, {"refresh": data["refresh"]},
                              format="json")
        self.assertEqual(refresh_resp.status_code, 200, refresh_resp.content)
        # 刷新会新建会话（新 jti），但不属于登录 → 不触发提醒
        self.assertEqual(len(self._messages()), 1)

    def test_template_missing_falls_back_to_default(self):
        MessageTemplate.objects.filter(code="login_new_device").delete()
        self._login()
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn("如非本人操作", msgs[0].content)

    def test_template_render_failure_falls_back(self):
        # 模板要求 {time}/{ip}/{device}，管理员改坏模板（多余占位符）→ 回退默认
        MessageTemplate.objects.filter(code="login_new_device").update(
            content="{time} {ip} {device} {missing_key}"
        )
        self._login()
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertIn("如非本人操作", msgs[0].content)

    def test_send_failure_never_blocks_login(self):
        with patch(
            "business.alert_system.services.InAppNotificationService.send_by_template",
            side_effect=Exception("boom"),
        ), patch(
            "business.alert_system.services.InAppNotificationService.send_to_user",
            side_effect=Exception("boom"),
        ):
            resp = self._login()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(self._messages()), 0)

    @override_settings(ALLOW_DEMO_LOGIN=True)
    def test_demo_login_triggers(self):
        resp = APIClient().post(
            self.demo_login_url,
            {"username": "demo_notify_user"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        demo_user = User.objects.get(username="demo_notify_user")
        self.assertEqual(len(self._messages(demo_user)), 1)
