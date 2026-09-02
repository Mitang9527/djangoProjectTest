"""QR 扫码登录端到端验证（Redis CAS 状态机）。

覆盖：
- 创建 ticket（匿名）→ 轮询 pending → 移动端确认 → PC 轮询一次性拿到 JWT → 再轮询 expired；
- 安全：一次性消费（Lua GETDEL）、重复确认 400、确认过期 ticket 404、confirm 需认证；
- Redis 不可用快速失败 503（不降级为永远 pending）；
- 交付的 access token 真实可调受保护接口（/api/v1/users/info/）。

说明：测试环境 Redis 通常不可达（_NullRedis 降级），
故注入内存 FakeRedisClient（对齐 RedisClient 封装签名）替代真实 Redis。
"""
import pickle

import pytest
from rest_framework.test import APIClient

from system.users.qr_login import QRLoginService
from tests.factories import UserFactory

CREATE_URL = "/api/v1/users/qr-login/tickets/"


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
    monkeypatch.setattr(QRLoginService, "_redis_ready", lambda: True)
    monkeypatch.setattr(QRLoginService, "_client", lambda: fake)
    return fake


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
class TestQRLoginFlow:
    """完整状态机流转"""

    def _create_ticket(self, client):
        resp = client.post(CREATE_URL)
        assert resp.status_code == 201, resp.content
        data = resp.json()["data"]
        assert data["ticket_id"]
        assert data["expires_in"] == QRLoginService.TICKET_TTL
        return data["ticket_id"]

    def test_full_flow(self, client, fake_redis):
        """创建 → pending → 确认 → 一次性 JWT → 再轮询 expired"""
        ticket = self._create_ticket(client)

        # 确认前轮询：pending
        resp = client.get(f"{CREATE_URL}{ticket}/")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"

        # 移动端确认（已登录）
        user = UserFactory()
        client.force_authenticate(user)
        resp = client.post(f"{CREATE_URL}{ticket}/confirm/")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "confirmed"

        # PC 端轮询：一次性拿到 JWT
        client.force_authenticate()  # 匿名轮询
        resp = client.get(f"{CREATE_URL}{ticket}/")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "confirmed"
        assert data["access"]
        assert data["refresh"]

        # 再次轮询：已消费 → expired
        resp = client.get(f"{CREATE_URL}{ticket}/")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "expired"

    def test_delivered_jwt_is_valid(self, client, fake_redis):
        """交付的 access 可调受保护接口"""
        ticket = self._create_ticket(client)
        user = UserFactory()
        client.force_authenticate(user)
        client.post(f"{CREATE_URL}{ticket}/confirm/")

        client.force_authenticate()
        data = client.get(f"{CREATE_URL}{ticket}/").json()["data"]
        assert data["status"] == "confirmed"

        # 用交付的 JWT 调受保护接口
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        resp = client.get("/api/v1/users/info/")
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == user.username

    def test_unknown_ticket_expired(self, client, fake_redis):
        """不存在的 ticket → expired（轮询不报错）"""
        resp = client.get(f"{CREATE_URL}deadbeef/")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "expired"


@pytest.mark.django_db
class TestQRLoginConfirm:
    """确认授权边界"""

    def _create_ticket(self, client):
        return client.post(CREATE_URL).json()["data"]["ticket_id"]

    def test_confirm_requires_auth(self, client, fake_redis):
        """匿名确认 → 401"""
        ticket = self._create_ticket(client)
        resp = client.post(f"{CREATE_URL}{ticket}/confirm/")
        assert resp.status_code in (401, 403)

    def test_confirm_unknown_ticket_404(self, client, fake_redis):
        client.force_authenticate(UserFactory())
        resp = client.post(f"{CREATE_URL}nope/confirm/")
        assert resp.status_code == 404
        assert resp.json()["errors"]["error_code"] == "ticket_not_found"

    def test_double_confirm_rejected(self, client, fake_redis):
        ticket = self._create_ticket(client)
        client.force_authenticate(UserFactory())
        assert client.post(f"{CREATE_URL}{ticket}/confirm/").status_code == 200
        resp = client.post(f"{CREATE_URL}{ticket}/confirm/")
        assert resp.status_code == 400
        assert resp.json()["errors"]["error_code"] == "ticket_already_confirmed"

    def test_confirm_issues_jwt_for_scanner(self, client, fake_redis):
        """JWT 归属确认者（user_id 写入 ticket）"""
        ticket = self._create_ticket(client)
        user = UserFactory()
        client.force_authenticate(user)
        client.post(f"{CREATE_URL}{ticket}/confirm/")
        stored = fake_redis.get(f"qr_login:{ticket}")
        assert stored["user_id"] == user.pk
        assert stored["status"] == "confirmed"


@pytest.mark.django_db
class TestQRLoginRedisUnavailable:
    """Redis 不可用快速失败（不降级为永远 pending）"""

    def test_create_fails_fast(self, client, monkeypatch):
        monkeypatch.setattr(QRLoginService, "_redis_ready", lambda: False)
        resp = client.post(CREATE_URL)
        assert resp.status_code == 503
        assert resp.json()["errors"]["error_code"] == "redis_unavailable"

    def test_poll_fails_fast(self, client, monkeypatch):
        monkeypatch.setattr(QRLoginService, "_redis_ready", lambda: False)
        resp = client.get(f"{CREATE_URL}whatever/")
        assert resp.status_code == 503

    def test_confirm_fails_fast(self, client, monkeypatch):
        monkeypatch.setattr(QRLoginService, "_redis_ready", lambda: False)
        client.force_authenticate(UserFactory())
        resp = client.post(f"{CREATE_URL}whatever/confirm/")
        assert resp.status_code == 503
