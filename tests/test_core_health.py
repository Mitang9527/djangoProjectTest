"""
核心功能测试：健康检查、系统状态
"""
import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.api
@pytest.mark.integration
class TestHealthCheck:
    """健康检查端点测试"""

    def test_health_check_returns_200(self, db, api_client):
        resp = api_client.get("/api/v1/health/")
        assert resp.status_code == status.HTTP_200_OK

    def test_health_check_returns_status_field(self, db, api_client):
        resp = api_client.get("/api/v1/health/")
        data = resp.json()
        assert "status" in data
        assert "db" in data

    def test_health_check_no_auth_required(self, db, api_client):
        """健康检查不需要认证"""
        resp = api_client.get("/api/v1/health/")
        assert resp.status_code != status.HTTP_401_UNAUTHORIZED
        assert resp.status_code != status.HTTP_403_FORBIDDEN
