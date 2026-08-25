"""
时效性密钥受保护接口测试。

验证 SecureInfoView 在「同步校验密钥正确性 + 时效性」后才返回信息：
- 缺密钥         → 401
- 密钥错误       → 401
- 密钥已禁用     → 401
- 密钥已过期     → 401
- 有效且未过期   → 200，并返回受保护数据
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from system.core.models import APIKey
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def key_user(db):
    return User.objects.create_user(username="secuser", password="SecPass123!")


def _client():
    return APIClient()


@pytest.mark.django_db
def test_secure_info_requires_key(key_user):
    """缺密钥必须拒绝（强制要求）。"""
    r = _client().get("/api/v1/core/secure-info/")
    assert r.status_code == 401


@pytest.mark.django_db
def test_secure_info_wrong_key(key_user):
    """错误密钥必须拒绝。"""
    r = _client().get("/api/v1/core/secure-info/", HTTP_X_API_KEY="sk-not-a-real-key")
    assert r.status_code == 401


@pytest.mark.django_db
def test_secure_info_valid_key(key_user):
    """有效且未过期的密钥返回 200 与受保护数据。"""
    k = APIKey.issue(key_user, "报表导出服务", ttl_seconds=3600)
    r = _client().get("/api/v1/core/secure-info/", HTTP_X_API_KEY=k.key)
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "success"
    data = payload["data"]
    assert data["owner"] == "secuser"
    assert data["key_name"] == "报表导出服务"
    assert data["secret_data"]["project"] == "djangoProjectTest"
    assert data["remaining_seconds"] > 0


@pytest.mark.django_db
def test_secure_info_bearer_header(key_user):
    """Authorization: Bearer <key> 同样可用。"""
    k = APIKey.issue(key_user, "svc", ttl_seconds=3600)
    r = _client().get("/api/v1/core/secure-info/", HTTP_AUTHORIZATION=f"Bearer {k.key}")
    assert r.status_code == 200


@pytest.mark.django_db
def test_secure_info_disabled(key_user):
    """已禁用密钥必须拒绝。"""
    k = APIKey.issue(key_user, "svc", ttl_seconds=3600)
    k.is_active = False
    k.save(update_fields=["is_active"])
    r = _client().get("/api/v1/core/secure-info/", HTTP_X_API_KEY=k.key)
    assert r.status_code == 401


@pytest.mark.django_db
def test_secure_info_expired(key_user):
    """已过期的密钥（时效性）必须拒绝。"""
    k = APIKey.issue(key_user, "svc", ttl_seconds=3600)
    k.expires_at = timezone.now() - timedelta(seconds=10)
    k.save(update_fields=["expires_at"])
    r = _client().get("/api/v1/core/secure-info/", HTTP_X_API_KEY=k.key)
    assert r.status_code == 401
