"""
测试数据工厂 — 使用 factory-boy 生成测试数据
避免在每个测试中手写 create() 调用
"""
import factory
from django.contrib.auth import get_user_model

from system.saas.models import Plan, Tenant, Role

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """用户工厂"""
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@test.com")
    password = factory.PostGenerationMethodCall("set_password", "TestPass123!")
    nickname = factory.LazyAttribute(lambda obj: obj.username)
    is_active = True


class AdminUserFactory(UserFactory):
    """管理员工厂"""
    username = "admin"
    is_staff = True
    is_superuser = True


class PlanFactory(factory.django.DjangoModelFactory):
    """套餐工厂"""
    class Meta:
        model = Plan

    name = factory.Sequence(lambda n: f"套餐 {n}")
    slug = factory.Sequence(lambda n: f"plan-{n}")
    description = "测试套餐"
    price = "99.00"
    max_users = 10
    max_storage_mb = 1024
    is_active = True


class TenantFactory(factory.django.DjangoModelFactory):
    """租户工厂"""
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"租户 {n}")
    slug = factory.Sequence(lambda n: f"tenant-{n}")
    description = "测试租户"
    status = Tenant.Status.ACTIVE
    plan = factory.SubFactory(PlanFactory)


class RoleFactory(factory.django.DjangoModelFactory):
    """角色工厂"""
    class Meta:
        model = Role

    name = factory.Sequence(lambda n: f"角色 {n}")
    slug = factory.Sequence(lambda n: f"role-{n}")
    description = "测试角色"
    is_system = False
