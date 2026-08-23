"""
API Key 生命周期管理测试（ApiKeyViewSet）。

覆盖：列表隔离（管理员看全部 / 普通用户仅看自己）、详情脱敏、吊销(PATCH)、
轮换（作废旧密钥 + 签发新密钥）、删除，以及普通用户越权访问他人密钥的隔离。

约定：所有响应经 CustomRenderer 五字段包装，列表数据在 data["results"]，
详情/签发/轮换在 data 直接为对象或字典。
"""
import pytest
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.test import APIClient

from system.core.models import APIKey, AuditLog


def _jwt_client(user):
    """用指定用户签发 JWT access token 构造已认证客户端。"""
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# --------------------------------------------------------------------------- #
# 列表隔离
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_admin_lists_all_keys(admin_user, regular_user):
    """管理员列表可见自己与他人的全部密钥。"""
    APIKey.issue(admin_user, "admin-key", ttl_seconds=3600)
    APIKey.issue(regular_user, "user-key", ttl_seconds=3600)

    client = _jwt_client(admin_user)
    resp = client.get("/api/api-keys/")
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["data"]["results"]
    names = {it["name"] for it in items}
    assert {"admin-key", "user-key"} <= names
    # 列表绝不回显明文 key
    assert all("key" not in it for it in items)
    # 列表展示脱敏
    assert all(it["masked_key"].startswith("sk-") for it in items)


@pytest.mark.django_db
def test_regular_user_lists_only_own(admin_user, regular_user):
    """普通用户列表仅能看到自己名下的密钥。"""
    APIKey.issue(admin_user, "admin-key", ttl_seconds=3600)
    APIKey.issue(regular_user, "user-key", ttl_seconds=3600)

    client = _jwt_client(regular_user)
    resp = client.get("/api/api-keys/")
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["data"]["results"]
    names = {it["name"] for it in items}
    assert names == {"user-key"}


# --------------------------------------------------------------------------- #
# 详情脱敏
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_detail_is_masked(regular_user):
    """详情返回脱敏 masked_key，且不含明文 key 字段。"""
    key = APIKey.issue(regular_user, "detail-key", ttl_seconds=3600)
    client = _jwt_client(regular_user)
    resp = client.get(f"/api/api-keys/{key.id}/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()["data"]
    assert body["masked_key"].startswith("sk-")
    assert "key" not in body
    assert body["id"] == key.id


# --------------------------------------------------------------------------- #
# 吊销 / 重新启用
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_revoke_via_patch(regular_user):
    """PATCH is_active=false 吊销密钥；is_usable 变为 False 并落审计。"""
    key = APIKey.issue(regular_user, "revoke-key", ttl_seconds=3600)
    client = _jwt_client(regular_user)
    resp = client.patch(f"/api/api-keys/{key.id}/", {"is_active": False}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()["data"]
    assert body["is_active"] is False
    assert body["is_usable"] is False

    key.refresh_from_db()
    assert key.is_active is False
    assert AuditLog.objects.filter(
        target_model="core_apikey", action="UPDATE",
        action_info__action="update", action_info__changes__is_active=False,
    ).exists()


@pytest.mark.django_db
def test_rename_via_patch(regular_user):
    """PATCH name 改名。"""
    key = APIKey.issue(regular_user, "old-name", ttl_seconds=3600)
    client = _jwt_client(regular_user)
    resp = client.patch(f"/api/api-keys/{key.id}/", {"name": "new-name"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["data"]["name"] == "new-name"
    key.refresh_from_db()
    assert key.name == "new-name"


# --------------------------------------------------------------------------- #
# 轮换
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_rotate_invalidates_old_and_issues_new(regular_user):
    """轮换：旧密钥被作废旧状态，新密钥返回明文且可用。"""
    old = APIKey.issue(regular_user, "rotate-key", ttl_seconds=3600)
    old_plain = old.key
    client = _jwt_client(regular_user)

    resp = client.post(f"/api/api-keys/{old.id}/rotate/")
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()["data"]
    new_plain = body["key"]
    assert new_plain.startswith("sk-")
    assert new_plain != old_plain
    assert body["masked_key"].startswith("sk-")

    old.refresh_from_db()
    assert old.is_active is False  # 旧密钥作废

    # 新明文哈希命中且仍启用；旧明文哈希已失效（被作废旧状态）
    assert APIKey.objects.filter(key_hash=APIKey.hash_key(new_plain), is_active=True).exists()
    assert not APIKey.objects.filter(key_hash=APIKey.hash_key(old_plain), is_active=True).exists()


# --------------------------------------------------------------------------- #
# 删除
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_delete_removes_key(regular_user):
    """DELETE 永久移除密钥，并落审计。"""
    key = APIKey.issue(regular_user, "delete-key", ttl_seconds=3600)
    kid = key.id
    client = _jwt_client(regular_user)
    resp = client.delete(f"/api/api-keys/{kid}/")
    assert resp.status_code == status.HTTP_200_OK
    assert not APIKey.objects.filter(id=kid).exists()
    assert AuditLog.objects.filter(
        target_model="core_apikey", action="DELETE", action_info__id=str(kid),
    ).exists()


# --------------------------------------------------------------------------- #
# 越权隔离：普通用户不能访问他人密钥
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_user_cannot_access_others_key(admin_user, regular_user):
    """普通用户访问管理员名下密钥的详情/更新/删除均被拒绝（404）。"""
    other = APIKey.issue(admin_user, "admin-only", ttl_seconds=3600)
    client = _jwt_client(regular_user)
    for method in ("get", "patch", "delete"):
        fn = getattr(client, method)
        if method == "patch":
            resp = fn(f"/api/api-keys/{other.id}/", {"is_active": False}, format="json")
        else:
            resp = fn(f"/api/api-keys/{other.id}/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND, method
    # 轮换同理
    resp = client.post(f"/api/api-keys/{other.id}/rotate/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
