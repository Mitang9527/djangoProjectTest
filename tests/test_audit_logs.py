"""阶段3 操作审计：LoginLog / OperationLog 回归。

对齐参考项目（Fast-Vben-Admin）：
  - 登录流程显式写 LoginLog（主登录 / 标准 JWT / DemoLogin），失败原因分类
    （bad_credentials / disabled / demo_login_disabled 等），显式调用不依赖信号；
  - OperationLogMiddleware 只记写操作（POST/PUT/PATCH/DELETE）+ /api/v1/ 前缀，
    跳过 /logs/*（防自审计）、登录/注册/改密端点；
  - 请求摘要脱敏（password/token/secret 等敏感键不落库）；
  - 500 异常也记录（try/finally）；
  - /logs/login + /logs/operation 租户隔离分页查询（普通用户无上下文 → 空）。

配套文件：scripts/verify_phase3.py（人工验证脚本，本文件为自动化回归）。
"""
import pytest
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from system.core.audit import record_login_log
from system.core.middleware import OperationLogMiddleware
from system.core.models import LoginLog, OperationLog
from system.saas.models import Department, Tenant, TenantMember
from system.users.models import User


# ============================================================
# record_login_log 直接调用
# ============================================================

class RecordLoginLogTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="审计租户", slug="audit_t")
        self.user = User.objects.create_user(
            username="audit_user", email="audit@example.com", password="Pass123!",
        )

    def test_success_record(self):
        rec = record_login_log(
            email=self.user.email, status='success',
            user=self.user, tenant_id=self.tenant.id,
        )
        self.assertIsNotNone(rec)
        row = LoginLog.objects.get(pk=rec.pk)
        self.assertEqual(row.status, "success")
        self.assertEqual(row.tenant_id, self.tenant.id)
        self.assertEqual(row.user_id, self.user.id)
        self.assertEqual(row.email, "audit@example.com")

    def test_failed_record_with_reason(self):
        rec = record_login_log(
            email="nobody@example.com", status='failed',
            failure_reason='bad_credentials',
        )
        row = LoginLog.objects.get(pk=rec.pk)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.failure_reason, "bad_credentials")
        self.assertIsNone(row.user)

    def test_silent_on_error(self):
        """写入失败静默（非法租户 ID 不抛异常）。"""
        rec = record_login_log(email="x@y.z", status='failed',
                               tenant_id="00000000-0000-0000-0000-000000000000")
        self.assertIsNone(rec)
        self.assertEqual(LoginLog.objects.count(), 0)


# ============================================================
# 登录流程 → LoginLog（端到端）
# ============================================================

class LoginFlowLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="login_user", email="login@example.com", password="GoodPass123!",
        )

    def test_main_login_success(self):
        c = APIClient()
        resp = c.post("/api/v1/users/login/",
                      {"username": "login_user", "password": "GoodPass123!"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        row = LoginLog.objects.latest("created_at")
        self.assertEqual(row.status, "success")
        self.assertEqual(row.email, "login@example.com")
        self.assertEqual(row.user_id, self.user.id)

    def test_main_login_failure(self):
        c = APIClient()
        resp = c.post("/api/v1/users/login/",
                      {"username": "login_user", "password": "Wrong!"}, format="json")
        self.assertEqual(resp.status_code, 401)
        row = LoginLog.objects.latest("created_at")
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.failure_reason, "bad_credentials")
        self.assertEqual(row.email, "login_user")

    def test_main_login_disabled(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        c = APIClient()
        resp = c.post("/api/v1/users/login/",
                      {"username": "login_user", "password": "GoodPass123!"}, format="json")
        self.assertEqual(resp.status_code, 403)
        row = LoginLog.objects.latest("created_at")
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.failure_reason, "disabled")

    def test_jwt_login_success_and_failure(self):
        c = APIClient()
        # 成功
        resp = c.post("/api/v1/users/jwt/login/",
                      {"username": "login_user", "password": "GoodPass123!"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        row = LoginLog.objects.latest("created_at")
        self.assertEqual(row.status, "success")
        # 失败
        resp = c.post("/api/v1/users/jwt/login/",
                      {"username": "login_user", "password": "Wrong!"}, format="json")
        self.assertEqual(resp.status_code, 401)
        row = LoginLog.objects.latest("created_at")
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.failure_reason, "bad_credentials")

    def test_demo_login_disabled_records_failure(self):
        """测试环境 ALLOW_DEMO_LOGIN=False → 403 且记失败日志。"""
        c = APIClient()
        resp = c.post("/api/v1/core/demo-login/", {"username": "anyone"}, format="json")
        self.assertEqual(resp.status_code, 403)
        row = LoginLog.objects.latest("created_at")
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.failure_reason, "demo_login_disabled")
        self.assertEqual(row.email, "anyone")


# ============================================================
# OperationLogMiddleware
# ============================================================

class OperationLogMiddlewareTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="op_admin", email="op_admin@example.com", password="Pass123!",
        )
        self.tenant = Tenant.objects.create(name="操作日志租户", slug="oplog_t")
        from rest_framework_simplejwt.tokens import RefreshToken
        self.access = str(RefreshToken.for_user(self.user).access_token)

    def _client(self):
        c = APIClient()
        c.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return c

    def test_write_operation_logged_with_attribution(self):
        c = self._client()
        before = OperationLog.objects.count()
        resp = c.post("/api/v1/saas/departments/",
                      {"name": "日志部门", "code": "log_dept"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(OperationLog.objects.count(), before + 1)
        op = OperationLog.objects.latest("created_at")
        self.assertEqual(op.module, "saas")
        self.assertEqual(op.action, "create")
        self.assertEqual(op.method, "POST")
        self.assertEqual(op.status_code, 201)
        self.assertEqual(op.tenant_id, self.tenant.id)
        self.assertEqual(op.user_id, self.user.id)
        self.assertEqual(op.email, "op_admin@example.com")
        self.assertGreaterEqual(op.duration_ms, 0)
        self.assertIn("log_dept", op.request_summary)

    def test_read_methods_not_logged(self):
        c = self._client()
        before = OperationLog.objects.count()
        # 列表 GET / POST 创建后，再 GET 不产生新行
        resp = c.get("/api/v1/saas/departments/")
        self.assertEqual(resp.status_code, 200)
        resp = c.head("/api/v1/saas/departments/")
        self.assertIn(resp.status_code, (200, 405))
        self.assertEqual(OperationLog.objects.count(), before)

    def test_logs_endpoints_not_self_logged(self):
        """防自审计死循环：/logs/* 自身不写 OperationLog。"""
        c = self._client()
        before = OperationLog.objects.count()
        resp = c.get("/api/v1/core/logs/operation/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(OperationLog.objects.count(), before)

    def test_login_endpoint_not_operation_logged(self):
        """登录端点由 LoginLog 记录，不重复进 OperationLog。"""
        c = APIClient()
        before_op = OperationLog.objects.count()
        before_login = LoginLog.objects.count()
        resp = c.post("/api/v1/users/login/",
                      {"username": "op_admin", "password": "Pass123!"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(OperationLog.objects.count(), before_op)
        self.assertEqual(LoginLog.objects.count(), before_login + 1)

    def test_request_summary_sanitizes_sensitive_keys(self):
        """摘要脱敏：password/token 等敏感键不落库。"""
        c = self._client()
        c.post("/api/v1/saas/departments/",
               {"name": "脱敏", "code": "sanitize",
                "password": "secret123", "refresh_token": "abc"}, format="json")
        op = OperationLog.objects.latest("created_at")
        self.assertNotIn("secret123", op.request_summary)
        self.assertNotIn("abc", op.request_summary)
        self.assertIn("sanitize", op.request_summary)

    def test_500_exception_still_logged(self):
        """try/finally：视图抛异常时也记录 500（不吞异常）。"""
        def boom(request):
            raise ValueError("boom")

        factory = RequestFactory()
        request = factory.post(
            "/api/v1/saas/departments/",
            data='{"name": "x"}', content_type="application/json",
        )
        mw = OperationLogMiddleware(boom)
        before = OperationLog.objects.count()
        with pytest.raises(ValueError):
            mw(request)
        self.assertEqual(OperationLog.objects.count(), before + 1)
        op = OperationLog.objects.latest("created_at")
        self.assertEqual(op.status_code, 500)
        self.assertEqual(op.method, "POST")


# ============================================================
# 日志查询端点租户隔离
# ============================================================

class LogQueryTenantIsolationTest(TestCase):
    def setUp(self):
        self.super_user = User.objects.create_superuser(
            username="query_admin", email="qa@example.com", password="Pass123!",
        )
        self.tenant_a = Tenant.objects.create(name="租户A", slug="qa_a")
        self.tenant_b = Tenant.objects.create(name="租户B", slug="qa_b")
        self.user_a = User.objects.create_user(
            username="user_a", email="ua@example.com", password="Pass123!")
        self.user_b = User.objects.create_user(
            username="user_b", email="ub@example.com", password="Pass123!")
        TenantMember.objects.create(tenant=self.tenant_a, user=self.user_a, is_active=True)
        TenantMember.objects.create(tenant=self.tenant_b, user=self.user_b, is_active=True)

        # 预置日志数据
        LoginLog.objects.create(tenant=self.tenant_a, user=self.user_a, email="ua@example.com")
        LoginLog.objects.create(tenant=self.tenant_b, user=self.user_b, email="ub@example.com")
        OperationLog.objects.create(
            tenant=self.tenant_a, user=self.user_a, email="ua@example.com",
            module="saas", action="create", method="POST", path="/api/v1/saas/x/",
            status_code=201,
        )
        OperationLog.objects.create(
            tenant=self.tenant_b, user=self.user_b, email="ub@example.com",
            module="saas", action="update", method="PATCH", path="/api/v1/saas/y/",
            status_code=200,
        )

    def _client(self, user, tenant_id=None):
        c = APIClient()
        c.force_authenticate(user)
        if tenant_id:
            c.credentials(HTTP_X_TENANT_ID=str(tenant_id))
        return c

    def test_superuser_sees_all_without_tenant_context(self):
        c = self._client(self.super_user)
        resp = c.get("/api/v1/core/logs/login/")
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 2)

        resp = c.get("/api/v1/core/logs/operation/")
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 2)

    def test_tenant_scoped_query(self):
        c = self._client(self.super_user, tenant_id=self.tenant_a.id)
        resp = c.get("/api/v1/core/logs/login/")
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["email"], "ua@example.com")

        resp = c.get("/api/v1/core/logs/operation/")
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "create")

    def test_regular_user_without_tenant_sees_none(self):
        c = self._client(self.user_a)
        resp = c.get("/api/v1/core/logs/login/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["results"], [])

        resp = c.get("/api/v1/core/logs/operation/")
        self.assertEqual(resp.json()["data"]["results"], [])

    def test_filter_by_status_and_method(self):
        c = self._client(self.super_user)
        resp = c.get("/api/v1/core/logs/login/", {"status": "success"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["data"]["results"]), 2)

        resp = c.get("/api/v1/core/logs/operation/", {"method": "PATCH"})
        results = resp.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "update")
