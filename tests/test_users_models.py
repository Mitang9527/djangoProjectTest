"""
用户模型单元测试
"""
import pytest
from django.contrib.auth import get_user_model

from tests.factories import UserFactory, AdminUserFactory

User = get_user_model()


@pytest.mark.unit
class TestUserModel:
    """User 模型测试"""

    def test_create_user(self, db):
        user = User.objects.create_user(
            username="newuser",
            email="new@test.com",
            password="Pass123!",
        )
        assert user.pk is not None
        assert user.username == "newuser"
        assert user.email == "new@test.com"
        assert user.check_password("Pass123!")
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_create_superuser(self, db):
        admin = User.objects.create_superuser(
            username="root",
            email="root@test.com",
            password="Root123!",
        )
        assert admin.is_staff is True
        assert admin.is_superuser is True

    def test_user_str_representation(self, db):
        user = UserFactory(username="alice")
        assert str(user) == "alice"

    def test_user_nickname_blank(self, db):
        user = User.objects.create_user(username="noname", password="Pass123!")
        assert user.nickname == ""

    def test_user_mobile_unique(self, db):
        UserFactory(username="u1", mobile="13800000001")
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            UserFactory(username="u2", mobile="13800000001")

    def test_user_factory_creates_valid_user(self, db):
        user = UserFactory()
        assert user.pk is not None
        assert user.check_password("TestPass123!")

    def test_admin_factory_creates_superuser(self, db):
        admin = AdminUserFactory()
        assert admin.is_staff is True
        assert admin.is_superuser is True


@pytest.mark.unit
class TestUserAuthentication:
    """用户认证测试"""

    def test_password_verification(self, db):
        user = UserFactory()
        assert user.check_password("TestPass123!")
        assert not user.check_password("wrong")

    def test_set_password(self, db):
        user = UserFactory()
        old_hash = user.password
        user.set_password("NewPass456!")
        user.save()
        user.refresh_from_db()
        assert user.password != old_hash
        assert user.check_password("NewPass456!")
