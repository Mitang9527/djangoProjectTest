"""阶段2 多租户：套餐/配额/初始化模板 + 生命周期状态机（端到端回归）。

对齐参考项目（Fast-Vben-Admin）：
  - TenantProfile / TenantPlanProfile / TenantInitializationTemplate 三模型；
  - POST /tenants/{id}/lifecycle 5 态生命周期（convert_to_formal / renew / freeze /
    unfreeze / archive），活跃→非活跃转变时吊销该租户全部会话；
  - GET /tenants/{id}/usage 用量统计（members / file_assets / storage_bytes vs 配额）；
  - 数据迁移种子：standard 默认套餐 + 默认初始化模板（RunPython 幂等）。

配套文件：scripts/verify_tenant_lifecycle.py（人工验证脚本，本文件为自动化回归）。
"""
import datetime as dt

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from system.saas.models import (
    Plan,
    Tenant,
    TenantInitializationTemplate,
    TenantMember,
    TenantPlanProfile,
    TenantProfile,
)
from system.saas.services import TenantProfileService
from system.users.models import User, UserSession


class TenantLifecycleServiceTest(TestCase):
    """TenantProfileService.operate_lifecycle 5 态状态机。"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="生命周期租户", slug="lc_t")
        self.profile = TenantProfileService.get_or_create_profile(self.tenant)

    def test_get_or_create_profile_idempotent(self):
        again = TenantProfileService.get_or_create_profile(self.tenant)
        self.assertEqual(again.tenant_id, self.profile.tenant_id)
        self.assertEqual(TenantProfile.objects.filter(tenant=self.tenant).count(), 1)
        # 默认 formal + effective_at
        self.assertEqual(self.profile.lifecycle_status, "formal")
        self.assertIsNotNone(self.profile.effective_at)

    def test_convert_to_formal_only_from_trial(self):
        self.profile.lifecycle_status = "trial"
        self.profile.trial_ends_at = timezone.now() + dt.timedelta(days=7)
        self.profile.save()
        r = TenantProfileService.operate_lifecycle(self.tenant, "convert_to_formal")
        self.assertNotIn("error", r)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.lifecycle_status, "formal")
        # formal 不可再转
        r = TenantProfileService.operate_lifecycle(self.tenant, "convert_to_formal")
        self.assertIn("error", r)

    def test_renew_recovers_expired_and_rejects_past(self):
        self.profile.lifecycle_status = "expired"
        self.profile.save()
        past = timezone.now() - dt.timedelta(days=1)
        r = TenantProfileService.operate_lifecycle(self.tenant, "renew", service_expires_at=past)
        self.assertIn("error", r)
        future = timezone.now() + dt.timedelta(days=365)
        r = TenantProfileService.operate_lifecycle(self.tenant, "renew", service_expires_at=future)
        self.assertNotIn("error", r)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.lifecycle_status, "formal")
        self.assertIsNotNone(self.profile.service_expires_at)

    def test_renew_rejects_archived(self):
        self.profile.lifecycle_status = "archived"
        self.profile.save()
        future = timezone.now() + dt.timedelta(days=30)
        r = TenantProfileService.operate_lifecycle(self.tenant, "renew", service_expires_at=future)
        self.assertIn("error", r)

    def test_freeze_requires_reason_and_revokes_sessions(self):
        user = User.objects.create_user(username="lc_user", password="Pass123!")
        TenantMember.objects.create(tenant=self.tenant, user=user, is_active=True)
        sess = UserSession.objects.create(
            user=user, tenant=self.tenant, token_jti="lc_jti",
            expires_at=timezone.now() + dt.timedelta(hours=1),
        )
        # 原因缺失被拒
        r = TenantProfileService.operate_lifecycle(self.tenant, "freeze", frozen_reason="  ")
        self.assertIn("error", r)
        # 冻结成功
        r = TenantProfileService.operate_lifecycle(self.tenant, "freeze", frozen_reason="欠费")
        self.assertNotIn("error", r)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.lifecycle_status, "frozen")
        self.assertEqual(self.profile.lifecycle_status_before_freeze, "formal")
        self.assertIsNotNone(self.profile.frozen_at)
        # tenant.status 同步
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, "suspended")
        # 会话吊销
        sess.refresh_from_db()
        self.assertIsNotNone(sess.revoked_at)
        # 冻结态不可再冻
        r = TenantProfileService.operate_lifecycle(self.tenant, "freeze", frozen_reason="再冻")
        self.assertIn("error", r)

    def test_unfreeze_restores_and_blocks_expired(self):
        self.profile.lifecycle_status = "frozen"
        self.profile.lifecycle_status_before_freeze = "formal"
        self.profile.frozen_at = timezone.now()
        self.profile.frozen_reason = "欠费"
        self.profile.save()
        r = TenantProfileService.operate_lifecycle(self.tenant, "unfreeze")
        self.assertNotIn("error", r)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.lifecycle_status, "formal")
        self.assertIsNone(self.profile.lifecycle_status_before_freeze)
        self.assertIsNone(self.profile.frozen_at)
        self.assertIsNone(self.profile.frozen_reason)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, "active")

        # 已到期冻结租户解冻须先续费
        t2 = Tenant.objects.create(name="到期冻结", slug="lc_t2")
        p2 = TenantProfileService.get_or_create_profile(t2)
        p2.lifecycle_status = "frozen"
        p2.lifecycle_status_before_freeze = "formal"
        p2.service_expires_at = timezone.now() - dt.timedelta(days=1)
        p2.frozen_at = timezone.now()
        p2.frozen_reason = "欠费"
        p2.save()
        r = TenantProfileService.operate_lifecycle(t2, "unfreeze")
        self.assertIn("error", r)

    def test_archive_clears_before_freeze(self):
        self.profile.lifecycle_status = "frozen"
        self.profile.lifecycle_status_before_freeze = "trial"
        self.profile.save()
        r = TenantProfileService.operate_lifecycle(self.tenant, "archive")
        self.assertNotIn("error", r)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.lifecycle_status, "archived")
        self.assertIsNone(self.profile.lifecycle_status_before_freeze)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, "cancelled")

    def test_unknown_action_rejected(self):
        r = TenantProfileService.operate_lifecycle(self.tenant, "explode")
        self.assertIn("error", r)

    def test_effective_status_time_derived(self):
        """时间派生：service_expires_at 到期 → expired（formal 存储态也派生）。"""
        self.profile.lifecycle_status = "formal"
        self.profile.service_expires_at = timezone.now() - dt.timedelta(days=1)
        self.profile.save()
        self.assertEqual(self.profile.effective_status(), "expired")
        self.assertFalse(self.profile.is_active)
        # frozen 不随时间派生
        self.profile.lifecycle_status = "frozen"
        self.profile.save()
        self.assertEqual(self.profile.effective_status(), "frozen")


class TenantUsageTest(TestCase):
    """GET /tenants/{id}/usage 用量统计。"""

    def test_usage_counts_members_and_plan_quota(self):
        tenant = Tenant.objects.create(name="用量租户", slug="usage_t")
        plan = Plan.objects.filter(is_default=True).first()
        tenant.plan = plan
        tenant.save()
        for i in range(3):
            u = User.objects.create_user(username=f"usage_u{i}", password="Pass123!")
            TenantMember.objects.create(tenant=tenant, user=u, is_active=True)
        # 非活跃成员不计
        u_inactive = User.objects.create_user(username="usage_inactive", password="Pass123!")
        TenantMember.objects.create(tenant=tenant, user=u_inactive, is_active=False)

        usage = TenantProfileService.get_usage(tenant)
        self.assertEqual(usage["members"], 3)
        self.assertEqual(usage["file_assets"], 0)  # 资产登记表未落地，占位
        self.assertEqual(usage["storage_bytes"], 0)
        self.assertEqual(usage["plan"]["id"], str(plan.id))
        self.assertEqual(usage["plan"]["max_users"], plan.max_users)
        self.assertEqual(usage["plan"]["max_file_assets"], plan.max_file_assets)


class TenantLifecycleApiTest(TestCase):
    """生命周期/用量 HTTP 端点。"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="lc_admin", password="Pass123!", is_staff=True, is_superuser=True,
        )
        self.tenant = Tenant.objects.create(name="API租户", slug="lc_api_t")
        TenantProfileService.get_or_create_profile(self.tenant)
        self.base = "/api/v1/saas/tenants"

    def _client(self):
        c = APIClient()
        c.force_authenticate(self.user)
        return c

    def test_freeze_via_api(self):
        c = self._client()
        resp = c.post(
            f"{self.base}/{self.tenant.id}/lifecycle/",
            {"action": "freeze", "frozen_reason": "逾期未续费"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertEqual(data["tenant"]["lifecycle_status"], "frozen")
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, "suspended")

    def test_freeze_requires_reason_via_api(self):
        c = self._client()
        resp = c.post(
            f"{self.base}/{self.tenant.id}/lifecycle/",
            {"action": "freeze"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_usage_via_api(self):
        c = self._client()
        resp = c.get(f"{self.base}/{self.tenant.id}/usage/")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()["data"]
        self.assertEqual(data["tenant_id"], str(self.tenant.id))
        self.assertIn("members", data)
        self.assertIn("plan", data)


class TenantPhase2SeedTest(TestCase):
    """数据迁移 0006 种子：默认套餐 / 默认初始化模板（测试库经 migrate 全量应用）。"""

    def test_default_plan_seeded(self):
        plan = Plan.objects.filter(is_default=True).first()
        self.assertIsNotNone(plan, "数据迁移应创建 standard 默认套餐")
        self.assertEqual(plan.slug, "standard")
        self.assertTrue(plan.is_active)
        profile = TenantPlanProfile.objects.filter(plan=plan).first()
        self.assertIsNotNone(profile, "默认套餐应有档案")

    def test_default_initialization_template_seeded(self):
        tmpl = TenantInitializationTemplate.objects.filter(code="standard").first()
        self.assertIsNotNone(tmpl, "数据迁移应创建 standard 初始化模板")
        self.assertTrue(tmpl.is_default)
        self.assertEqual(tmpl.root_department_code, "headquarters")
        self.assertEqual(tmpl.root_department_name, "总部")
        # 全部种子开关默认开启
        self.assertTrue(tmpl.seed_posts)
        self.assertTrue(tmpl.seed_mail_accounts)
