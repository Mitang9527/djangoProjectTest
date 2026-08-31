# -*- coding: utf-8 -*-
"""验证阶段2：TenantProfileService 生命周期状态机 + usage 用量统计。

运行: .venv/Scripts/python.exe manage.py shell -c "exec(open('scripts/verify_tenant_lifecycle.py', encoding='utf-8').read())"
"""
import datetime as _dt

from django.utils import timezone

from system.saas.models import Tenant, TenantMember, TenantProfile, Plan, Role
from system.users.models import User
from system.saas.services import TenantProfileService as Svc

PASS = []
FAIL = []

# 清理上次运行残留（slug 前缀 lf_）
Tenant.objects.filter(slug__startswith="lf_").delete()
User.objects.filter(username__startswith="lf_").delete()


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {extra}")


def mk_tenant(name, status="active"):
    t = Tenant.objects.create(name=name, slug=name, status=status)
    Svc.get_or_create_profile(t)
    return t


def mk_user(username):
    u = User.objects.create_user(username=username, password="Test@12345")
    return u


print("== 1. get_or_create_profile 幂等 ==")
t1 = mk_tenant("lf_t1")
p1 = t1.profile
check("首次创建 formal", p1.lifecycle_status == "formal" and p1.effective_at is not None)
p1b = Svc.get_or_create_profile(t1)
check("幂等不重建", p1b.tenant_id == p1.tenant_id and TenantProfile.objects.count() >= 1)

print("== 2. convert_to_formal ==")
t2 = mk_tenant("lf_t2")
p2 = t2.profile
p2.lifecycle_status = "trial"
p2.trial_ends_at = timezone.now() + _dt.timedelta(days=7)
p2.save()
r = Svc.operate_lifecycle(t2, "convert_to_formal")
check("trial→formal 成功", "error" not in r and t2.profile.lifecycle_status == "formal", r)
r = Svc.operate_lifecycle(t2, "convert_to_formal")
check("formal 再转被拒", "error" in r, r)

print("== 3. renew 状态机 ==")
t3 = mk_tenant("lf_t3")
p3 = t3.profile
p3.lifecycle_status = "expired"
p3.save()
r = Svc.operate_lifecycle(t3, "renew", service_expires_at=timezone.now() - _dt.timedelta(days=1))
check("过期时间被拒", "error" in r, r)
future = timezone.now() + _dt.timedelta(days=365)
r = Svc.operate_lifecycle(t3, "renew", service_expires_at=future)
check("expired→formal 恢复", "error" not in r and t3.profile.lifecycle_status == "formal", r)
check("service_expires_at 写入", t3.profile.service_expires_at is not None)

print("== 4. freeze：原因/状态校验 + 会话吊销 ==")
t4 = mk_tenant("lf_t4")
p4 = t4.profile
p4.lifecycle_status = "formal"
p4.save()
u4 = mk_user("lf_u4")
TenantMember.objects.create(tenant=t4, user=u4, is_active=True)
from system.users.models import UserSession
import uuid as _uuid
sess = UserSession.objects.create(
    user=u4, tenant=t4, token_jti=str(_uuid.uuid4()),
    expires_at=timezone.now() + _dt.timedelta(days=1),
)
r = Svc.operate_lifecycle(t4, "freeze", frozen_reason="  ")
check("无原因被拒", "error" in r, r)
r = Svc.operate_lifecycle(t4, "freeze", frozen_reason="欠费")
check("freeze 成功", "error" not in r and t4.profile.lifecycle_status == "frozen", r)
check("before_freeze=formal", t4.profile.lifecycle_status_before_freeze == "formal")
check("frozen_at 写入", t4.profile.frozen_at is not None)
check("tenant.status→suspended", t4.status == "suspended", t4.status)
sess.refresh_from_db()
check("冻结吊销会话", sess.revoked_at is not None)
r = Svc.operate_lifecycle(t4, "freeze", frozen_reason="再冻")
check("frozen 再冻被拒", "error" in r, r)

print("== 5. unfreeze：过期拦截 / 恢复 ==")
t5 = mk_tenant("lf_t5")
p5 = t5.profile
p5.lifecycle_status = "frozen"
p5.lifecycle_status_before_freeze = "formal"
p5.frozen_at = timezone.now()
p5.frozen_reason = "欠费"
p5.save()
r = Svc.operate_lifecycle(t5, "unfreeze")
check("冻结且未过期可解冻", "error" not in r and t5.profile.lifecycle_status == "formal", r)
check("解冻清 before_freeze/frozen_at", t5.profile.lifecycle_status_before_freeze is None and t5.profile.frozen_at is None)
check("tenant.status→active", t5.status == "active", t5.status)
# 过期冻结租户解冻应被拒
t5b = mk_tenant("lf_t5b")
p5b = t5b.profile
p5b.lifecycle_status = "frozen"
p5b.lifecycle_status_before_freeze = "formal"
p5b.service_expires_at = timezone.now() - _dt.timedelta(days=1)
p5b.frozen_at = timezone.now()
p5b.frozen_reason = "欠费"
p5b.save()
r = Svc.operate_lifecycle(t5b, "unfreeze")
check("过期冻结须先续费", "error" in r, r)

print("== 6. archive ==")
t6 = mk_tenant("lf_t6")
p6 = t6.profile
p6.lifecycle_status = "frozen"
p6.lifecycle_status_before_freeze = "trial"
p6.save()
r = Svc.operate_lifecycle(t6, "archive")
check("archive 成功", "error" not in r and t6.profile.lifecycle_status == "archived", r)
check("archive 清 before_freeze", t6.profile.lifecycle_status_before_freeze is None)
check("tenant.status→cancelled", t6.status == "cancelled", t6.status)
r = Svc.operate_lifecycle(t6, "renew", service_expires_at=timezone.now() + _dt.timedelta(days=30))
check("archived 不可续费", "error" in r, r)

print("== 7. 非法动作 ==")
r = Svc.operate_lifecycle(t1, "explode")
check("非法动作被拒", "error" in r, r)

print("== 8. usage 统计 ==")
t8 = mk_tenant("lf_t8")
u8a = mk_user("lf_u8a")
u8b = mk_user("lf_u8b")
TenantMember.objects.create(tenant=t8, user=u8a, is_active=True)
TenantMember.objects.create(tenant=t8, user=u8b, is_active=True)
plan = Plan.objects.filter(is_default=True).first()
t8.plan = plan
t8.save()
usage = Svc.get_usage(t8)
check("members=2", usage["members"] == 2, usage)
check("plan 配额字段", usage["plan"] and usage["plan"]["max_users"] == plan.max_users, usage)

print("== 9. 路由存在 ==")
from django.urls import resolve
for path in [
    "/api/v1/saas/tenants/xxx/lifecycle/",
    "/api/v1/saas/tenants/xxx/usage/",
]:
    try:
        resolve(path)
        check(f"路由可解析 {path}", True)
    except Exception as e:
        check(f"路由可解析 {path}", False, str(e))

print(f"\n===== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
if FAIL:
    raise SystemExit(1)
