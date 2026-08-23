"""
ApiKeyViewSet 签发接口测试（POST /api/api-keys/，旧 CreateApiKeyView 的接口版）。
覆盖：未认证 / 非管理员 / 管理员自签 / 管理员代发 / 永久密钥 / 未知归属用户 / 缺参。
"""
import pytest
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.test import APIClient

from system.core.models import AuditLog


def _jwt_client(user):
    """用指定用户签发 JWT access token 构造已认证客户端。"""
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_unauthenticated_is_forbidden(api_client):
    """未携带 token → 认证层直接拒绝 → 401。"""
    resp = api_client.post("/api/api-keys/", {"name": "x"}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_regular_user_is_forbidden(regular_user):
    """普通用户（非 is_staff）→ 403。"""
    client = _jwt_client(regular_user)
    resp = client.post("/api/api-keys/", {"name": "x"}, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_admin_issues_key_for_self(admin_user):
    """管理员自签 → 201，明文以 sk- 开头，落审计日志。"""
    client = _jwt_client(admin_user)
    resp = client.post("/api/api-keys/", {"name": "报表导出", "ttl": 3600}, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()["data"]
    assert body["key"].startswith("sk-")
    assert body["owner"] == "admin"
    assert body["is_permanent"] is False
    assert body["expires_at"] is not None
    assert AuditLog.objects.filter(target_model="core_apikey", action="CREATE").exists()


@pytest.mark.django_db
def test_admin_issues_permanent_key(admin_user):
    """ttl=0 → 永不过期（expires_at 为 None, is_permanent=True）。"""
    client = _jwt_client(admin_user)
    resp = client.post("/api/api-keys/", {"name": "永久服务账号", "ttl": 0}, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()["data"]
    assert body["is_permanent"] is True
    assert body["expires_at"] is None


@pytest.mark.django_db
def test_admin_issues_for_other_user(admin_user, second_user):
    """管理员可为他人代发密钥。"""
    client = _jwt_client(admin_user)
    resp = client.post(
        "/api/api-keys/",
        {"name": "代发密钥", "owner_username": "testuser2"},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["data"]["owner"] == "testuser2"


@pytest.mark.django_db
def test_admin_issues_for_unknown_user(admin_user):
    """归属用户不存在 → 400。"""
    client = _jwt_client(admin_user)
    resp = client.post(
        "/api/api-keys/",
        {"name": "x", "owner_username": "nobody"},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_missing_name_rejected(admin_user):
    """缺少 name → 400 参数校验失败。"""
    client = _jwt_client(admin_user)
    resp = client.post("/api/api-keys/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
