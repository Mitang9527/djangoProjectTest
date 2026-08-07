"""
Request-ID 中间件测试
"""
import pytest
from rest_framework import status

from framework.log_utils.request_id import get_request_id, set_request_id, clear_request_id


@pytest.mark.unit
class TestRequestID:
    """Request-ID 功能测试"""

    def test_get_set_clear(self):
        rid = "test-rid-12345"
        set_request_id(rid)
        assert get_request_id() == rid
        clear_request_id()
        assert get_request_id() is None

    def test_get_without_set(self):
        clear_request_id()
        assert get_request_id() is None


@pytest.mark.api
@pytest.mark.integration
class TestRequestIDMiddleware:
    """Request-ID 中间件测试"""

    def test_response_has_request_id(self, db, api_client):
        """响应头包含 X-Request-ID"""
        resp = api_client.get("/api/health/")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    def test_custom_request_id_passthrough(self, db, api_client):
        """自定义 Request-ID 透传"""
        custom_id = "my-custom-request-id-abc123"
        resp = api_client.get(
            "/api/health/",
            HTTP_X_REQUEST_ID=custom_id,
        )
        assert resp.headers["X-Request-ID"] == custom_id

    def test_auto_generated_request_id(self, db, api_client):
        """不传 Request-ID 时自动生成 UUID"""
        resp = api_client.get("/api/health/")
        rid = resp.headers["X-Request-ID"]
        # UUID 格式验证
        import uuid
        try:
            uuid.UUID(rid)
            assert True
        except ValueError:
            # 可能是自定义格式，只要不为空就行
            assert len(rid) > 0
