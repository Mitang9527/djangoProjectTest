"""站内信 + 消息模板 端到端验证。

覆盖：
- 服务层: send_to_user / send_to_users(单/多/空) / send_by_template(命中渲染/不存在/未启用) / unread_count；
- 模型层: mark_read 幂等、is_read；
- 站内信 API: 列表仅本人可见、unread_count、mark_read、read_all、只读(POST 405)；
- 模板 API: 管理员可写、普通用户只读(写 403)、code 唯一/非法字符校验。
"""
import pytest
from rest_framework.test import APIClient

from business.alert_system.models import InAppMessage, MessageTemplate
from business.alert_system.services import InAppNotificationService
from tests.factories import UserFactory, AdminUserFactory

INBOX_URL = "/api/v1/alert_system/in-app-messages/"
TEMPLATE_URL = "/api/v1/alert_system/message-templates/"


# ==================================================
# 服务层
# ==================================================

@pytest.mark.django_db
class TestInAppService:
    """InAppNotificationService 发送/渲染/计数"""

    def test_send_to_user(self):
        user = UserFactory()
        msg = InAppNotificationService.send_to_user(user, "标题", "内容", level="warning")
        assert msg.user_id == user.id
        assert msg.title == "标题"
        assert msg.content == "内容"
        assert msg.level == "warning"
        assert msg.read_at is None
        assert InAppMessage.objects.count() == 1

    def test_send_to_users_single(self):
        user = UserFactory()
        msgs = InAppNotificationService.send_to_users([user], "t", "c")
        assert len(msgs) == 1
        assert InAppMessage.objects.count() == 1

    def test_send_to_users_bulk(self):
        users = [UserFactory(), UserFactory(), UserFactory()]
        msgs = InAppNotificationService.send_to_users(users, "t", "c")
        assert len(msgs) == 3
        assert InAppMessage.objects.count() == 3
        assert {m.user_id for m in msgs} == {u.id for u in users}

    def test_send_to_users_empty(self):
        assert InAppNotificationService.send_to_users([], "t", "c") == []
        assert InAppMessage.objects.count() == 0

    def test_send_by_template_renders(self):
        user = UserFactory()
        MessageTemplate.objects.create(
            code="welcome",
            title="欢迎 {name}",
            content="你好 {name}，欢迎加入 {tenant}",
        )
        msg = InAppNotificationService.send_by_template(
            user, "welcome", context={"name": "张三", "tenant": "Demo 租户"}
        )
        assert msg.title == "欢迎 张三"
        assert msg.content == "你好 张三，欢迎加入 Demo 租户"

    def test_send_by_template_missing(self):
        user = UserFactory()
        assert InAppNotificationService.send_by_template(user, "nope") is None
        assert InAppMessage.objects.count() == 0

    def test_send_by_template_inactive(self):
        user = UserFactory()
        MessageTemplate.objects.create(code="off", title="t", content="c", is_active=False)
        assert InAppNotificationService.send_by_template(user, "off") is None
        assert InAppMessage.objects.count() == 0

    def test_unread_count(self):
        user = UserFactory()
        InAppNotificationService.send_to_user(user, "a", "1")
        InAppNotificationService.send_to_user(user, "b", "2")
        msg = InAppMessage.objects.get(title="a")
        msg.mark_read()
        assert InAppNotificationService.unread_count(user) == 1


# ==================================================
# 模型层
# ==================================================

@pytest.mark.django_db
class TestInAppMessageModel:
    """mark_read / is_read 行为"""

    def test_mark_read_idempotent(self):
        user = UserFactory()
        msg = InAppNotificationService.send_to_user(user, "t", "c")
        assert not msg.is_read
        msg.mark_read()
        assert msg.is_read
        read_at = msg.read_at
        msg.mark_read()  # 幂等：不重复写库、不改变时间
        assert msg.read_at == read_at
        assert InAppMessage.objects.filter(read_at=read_at).count() == 1


# ==================================================
# 站内信 API
# ==================================================

@pytest.mark.django_db
class TestInAppMessageApi:
    """收件箱列表/未读数/标记已读"""

    @pytest.fixture(autouse=True)
    def _client(self):
        self.client = APIClient()

    def _auth(self, user):
        self.client.force_authenticate(user)

    def test_list_only_own_messages(self):
        user_a = UserFactory()
        user_b = UserFactory()
        InAppNotificationService.send_to_user(user_a, "给A", "1")
        InAppNotificationService.send_to_user(user_b, "给B", "2")
        self._auth(user_a)
        resp = self.client.get(INBOX_URL)
        assert resp.status_code == 200
        data = resp.json()["data"]
        titles = [item["title"] for item in data["results"]]
        assert titles == ["给A"]
        assert resp.json()["status"] == "success"

    def test_unread_count_endpoint(self):
        user = UserFactory()
        InAppNotificationService.send_to_user(user, "a", "1")
        InAppNotificationService.send_to_user(user, "b", "2")
        InAppMessage.objects.get(title="a").mark_read()
        self._auth(user)
        resp = self.client.get(f"{INBOX_URL}unread_count/")
        assert resp.status_code == 200
        assert resp.json()["data"]["unread_count"] == 1

    def test_mark_read(self):
        user = UserFactory()
        InAppNotificationService.send_to_user(user, "a", "1")
        self._auth(user)
        msg = InAppMessage.objects.get()
        resp = self.client.post(f"{INBOX_URL}{msg.id}/mark_read/")
        assert resp.status_code == 200
        assert resp.json()["data"]["code"] == "mark_read_ok"
        msg.refresh_from_db()
        assert msg.read_at is not None

    def test_mark_read_again_idempotent(self):
        user = UserFactory()
        InAppNotificationService.send_to_user(user, "a", "1")
        self._auth(user)
        msg = InAppMessage.objects.get()
        first = self.client.post(f"{INBOX_URL}{msg.id}/mark_read/")
        assert first.status_code == 200
        msg.refresh_from_db()
        read_at = msg.read_at
        second = self.client.post(f"{INBOX_URL}{msg.id}/mark_read/")
        assert second.status_code == 200
        msg.refresh_from_db()
        assert msg.read_at == read_at  # 幂等：时间不变

    def test_read_all(self):
        user = UserFactory()
        InAppNotificationService.send_to_user(user, "a", "1")
        InAppNotificationService.send_to_user(user, "b", "2")
        self._auth(user)
        resp = self.client.post(f"{INBOX_URL}read_all/")
        assert resp.status_code == 200
        assert resp.json()["data"]["code"] == "read_all_ok"
        assert InAppMessage.objects.filter(user=user, read_at__isnull=True).count() == 0

    def test_inbox_is_read_only(self):
        """站内信由服务端产生，客户端 POST 直接 405"""
        user = UserFactory()
        self._auth(user)
        resp = self.client.post(INBOX_URL, {"title": "x", "content": "y"})
        assert resp.status_code == 405

    def test_cannot_read_others_message(self):
        """越权访问他人消息 → 404（queryset 已按当前用户过滤）"""
        user_a = UserFactory()
        user_b = UserFactory()
        msg = InAppNotificationService.send_to_user(user_a, "a", "1")
        self._auth(user_b)
        resp = self.client.post(f"{INBOX_URL}{msg.id}/mark_read/")
        assert resp.status_code == 404


# ==================================================
# 模板 API
# ==================================================

@pytest.mark.django_db
class TestMessageTemplateApi:
    """模板 CRUD 权限与校验"""

    @pytest.fixture(autouse=True)
    def _client(self):
        self.client = APIClient()

    def _auth(self, user):
        self.client.force_authenticate(user)

    def test_admin_can_create(self):
        self._auth(AdminUserFactory())
        resp = self.client.post(
            TEMPLATE_URL,
            {"code": "welcome", "title": "欢迎", "content": "你好 {name}"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert MessageTemplate.objects.filter(code="welcome").exists()

    def test_normal_user_read_only(self):
        """普通用户可读模板，但写操作 403"""
        MessageTemplate.objects.create(code="welcome", title="欢迎", content="你好")
        before = MessageTemplate.objects.count()
        self._auth(UserFactory())
        assert self.client.get(TEMPLATE_URL).status_code == 200
        resp = self.client.post(
            TEMPLATE_URL,
            {"code": "x", "title": "t", "content": "c"},
            format="json",
        )
        assert resp.status_code == 403
        # 播种模板（如 login_new_device）不影响断言：失败写操作不应新增任何模板
        assert MessageTemplate.objects.count() == before

    def test_duplicate_code_rejected(self):
        self._auth(AdminUserFactory())
        MessageTemplate.objects.create(code="welcome", title="旧", content="旧")
        resp = self.client.post(
            TEMPLATE_URL,
            {"code": "welcome", "title": "新", "content": "新"},
            format="json",
        )
        assert resp.status_code == 400
        assert "errors" in resp.json()

    def test_duplicate_code_case_insensitive(self):
        """code 大小写不敏感唯一（WELCOME 与 welcome 冲突）"""
        self._auth(AdminUserFactory())
        MessageTemplate.objects.create(code="welcome", title="旧", content="旧")
        resp = self.client.post(
            TEMPLATE_URL,
            {"code": "WELCOME", "title": "新", "content": "新"},
            format="json",
        )
        assert resp.status_code == 400

    def test_invalid_code_chars_rejected(self):
        self._auth(AdminUserFactory())
        resp = self.client.post(
            TEMPLATE_URL,
            {"code": "bad code!", "title": "t", "content": "c"},
            format="json",
        )
        assert resp.status_code == 400

    def test_template_update_by_admin(self):
        self._auth(AdminUserFactory())
        tpl = MessageTemplate.objects.create(code="welcome", title="欢迎", content="你好")
        resp = self.client.patch(
            f"{TEMPLATE_URL}{tpl.id}/",
            {"is_active": False},
            format="json",
        )
        assert resp.status_code == 200
        tpl.refresh_from_db()
        assert not tpl.is_active
