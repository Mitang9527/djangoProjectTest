"""
用户 API 端点测试
"""
import pytest
from rest_framework import status

from tests.factories import UserFactory


@pytest.mark.api
@pytest.mark.integration
class TestUserLoginAPI:
    """登录接口测试"""

    def test_login_success(self, db, api_client):
        """登录成功返回 JWT token"""
        user = UserFactory(username="loginuser")
        user.set_password("Pass123!")
        user.save()

        resp = api_client.post(
            "/api/v1/users/login/",
            data={"username": "loginuser", "password": "Pass123!"},
            format="json",
            HTTP_ACCEPT="application/json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json().get("data", resp.json())
        assert "access" in body
        assert "refresh" in body

    def test_login_wrong_password(self, db, api_client):
        """密码错误返回 401"""
        UserFactory(username="loginuser")
        resp = api_client.post(
            "/api/v1/users/login/",
            data={"username": "loginuser", "password": "wrongpass"},
            format="json",
            HTTP_ACCEPT="application/json",
        )
        assert resp.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED)

    def test_login_nonexistent_user(self, db, api_client):
        """不存在的用户返回错误"""
        resp = api_client.post(
            "/api/v1/users/login/",
            data={"username": "ghost", "password": "Pass123!"},
            format="json",
            HTTP_ACCEPT="application/json",
        )
        assert resp.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED)

    def test_login_missing_fields(self, db, api_client):
        """缺少字段返回 400"""
        resp = api_client.post(
            "/api/v1/users/login/",
            data={},
            format="json",
            HTTP_ACCEPT="application/json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.api
@pytest.mark.integration
class TestJWTTokenAPI:
    """JWT Token 接口测试"""

    def test_jwt_login(self, db, api_client):
        """JWT 登录获取 token"""
        user = UserFactory(username="jwtuser")
        user.set_password("Pass123!")
        user.save()

        resp = api_client.post(
            "/api/v1/users/jwt/login/",
            data={"username": "jwtuser", "password": "Pass123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        # CustomRenderer 将数据包裹在 data 字段中
        token_data = data.get("data", data)
        assert "access" in token_data
        assert "refresh" in token_data

    def test_jwt_refresh(self, db, api_client):
        """JWT refresh token 刷新"""
        user = UserFactory(username="jwtuser")
        user.set_password("Pass123!")
        user.save()

        # 先登录获取 token
        resp = api_client.post(
            "/api/v1/users/jwt/login/",
            data={"username": "jwtuser", "password": "Pass123!"},
            format="json",
        )
        login_data = resp.json().get("data", resp.json())
        refresh_token = login_data["refresh"]

        # 刷新 token
        resp = api_client.post(
            "/api/v1/users/jwt/refresh/",
            data={"refresh": refresh_token},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        refresh_data = resp.json().get("data", resp.json())
        # refresh 端点至少返回 refresh 或 access token
        assert "refresh" in refresh_data or "access" in refresh_data

    def test_jwt_verified_request(self, db, jwt_auth_client):
        """JWT 认证后的请求应该能通过"""
        resp = jwt_auth_client.get("/api/v1/users/info/")
        assert resp.status_code != status.HTTP_401_UNAUTHORIZED
