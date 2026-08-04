"""
项目级 Pytest 配置
提供公共 fixtures：数据库、用户、API 客户端、工厂等
"""
import os
import sys
from pathlib import Path

# ================================================================
# 在任何 Django 导入之前，加载测试环境变量
# ================================================================
_PROJECT_ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only-at-least-10-chars")
os.environ.setdefault("JWT_SIGNING_KEY", "test-jwt-signing-key-independent-from-secret-key-at-least-10c")
os.environ.setdefault("API_SECRET_KEY", "test-api-secret-key-not-for-production-use-at-least-10-chars")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("ENV", "TEST")
os.environ.setdefault("PROJECT_NAME", "DjangoTest")
os.environ.setdefault("TESTER_NAME", "Pytest")
os.environ.setdefault("ALLOWED_HOSTS", "*")

# 尝试加载 .env.test 文件（如果存在）
_env_test = _PROJECT_ROOT / ".env.test"
if _env_test.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_test, override=False)
    except ImportError:
        pass

# 确保 apps 目录在 path 中
sys.path.insert(0, str(_PROJECT_ROOT / "apps"))

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


# ================================================================
# Pytest 标记注册
# ================================================================
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: 单元测试 (快速, 无外部依赖)")
    config.addinivalue_line("markers", "integration: 集成测试 (需要 DB)")
    config.addinivalue_line("markers", "slow: 慢测试 (>1s)")
    config.addinivalue_line("markers", "api: API 端点测试")


# ================================================================
# 核心 Fixtures
# ================================================================

@pytest.fixture
def api_client():
    """DRF API 客户端（未认证）"""
    return APIClient()


@pytest.fixture
def authenticated_client(db, regular_user):
    """已认证的 API 客户端（普通用户）"""
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def admin_client(db, admin_user):
    """已认证的 API 客户端（管理员）"""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def regular_user(db):
    """普通用户"""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="TestPass123!",
        nickname="测试用户",
    )


@pytest.fixture
def admin_user(db):
    """超级管理员"""
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="AdminPass123!",
    )


@pytest.fixture
def second_user(db):
    """第二个普通用户（用于测试隔离）"""
    return User.objects.create_user(
        username="testuser2",
        email="test2@example.com",
        password="TestPass456!",
    )


# ================================================================
# JWT Token Fixtures
# ================================================================

@pytest.fixture
def jwt_tokens(regular_user):
    """获取 JWT access + refresh token"""
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(regular_user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


@pytest.fixture
def jwt_auth_client(db, jwt_tokens):
    """使用 JWT 认证的 API 客户端"""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    return client
