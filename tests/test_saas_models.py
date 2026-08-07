"""
SaaS 模型单元测试
"""
import pytest
from decimal import Decimal

from system.saas.models import Plan, Tenant, PlanFeature, TenantSubscription
from tests.factories import PlanFactory, TenantFactory, UserFactory


@pytest.mark.unit
class TestPlanModel:
    """套餐模型测试"""

    def test_create_plan(self, db):
        plan = PlanFactory(name="专业版", slug="pro", price="199.00")
        assert plan.pk is not None
        assert plan.name == "专业版"
        assert str(plan.price) == "199.00"
        assert plan.is_active is True

    def test_plan_str(self, db):
        plan = PlanFactory(name="企业版")
        assert str(plan) == "企业版"

    def test_plan_default_currency(self, db):
        plan = PlanFactory()
        assert plan.currency == "CNY"

    def test_plan_defaults(self, db):
        plan = PlanFactory()
        assert plan.max_users == 10
        assert plan.max_storage_mb == 1024

    def test_plan_status_choices(self, db):
        plan = PlanFactory(is_active=False)
        assert plan.is_active is False


@pytest.mark.unit
class TestPlanFeatureModel:
    """套餐功能模型测试"""

    def test_create_feature(self, db):
        plan = PlanFactory()
        feature = PlanFeature.objects.create(
            plan=plan,
            feature_code="api_access",
            feature_name="API 访问",
        )
        assert feature.pk is not None
        assert feature.plan == plan
        assert feature.is_enabled is True

    def test_feature_unique_together(self, db):
        plan = PlanFactory()
        PlanFeature.objects.create(plan=plan, feature_code="x", feature_name="X")
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            PlanFeature.objects.create(plan=plan, feature_code="x", feature_name="Y")

    def test_feature_str(self, db):
        plan = PlanFactory(name="基础版")
        feature = PlanFeature.objects.create(plan=plan, feature_code="y", feature_name="Y功能")
        assert "基础版" in str(feature)


@pytest.mark.unit
class TestTenantModel:
    """租户模型测试"""

    def test_create_tenant(self, db):
        tenant = TenantFactory(name="Acme公司", slug="acme")
        assert tenant.pk is not None
        assert tenant.name == "Acme公司"
        assert tenant.status == Tenant.Status.ACTIVE

    def test_tenant_str(self, db):
        tenant = TenantFactory(name="TestCo")
        assert str(tenant) == "TestCo"

    def test_tenant_with_plan(self, db):
        plan = PlanFactory(name="专业版")
        tenant = TenantFactory(name="TestCo", plan=plan)
        assert tenant.plan == plan

    def test_tenant_status_choices(self, db):
        tenant = TenantFactory(status=Tenant.Status.SUSPENDED)
        assert tenant.status == "suspended"


@pytest.mark.unit
class TestTenantSubscriptionModel:
    """租户订阅模型测试"""

    def test_create_subscription(self, db):
        tenant = TenantFactory()
        plan = PlanFactory()
        sub = TenantSubscription.objects.create(tenant=tenant, plan=plan)
        assert sub.pk is not None
        assert sub.status == TenantSubscription.Status.TRIAL
        assert sub.auto_renew is True
