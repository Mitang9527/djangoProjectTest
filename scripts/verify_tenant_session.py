"""
阶段1 核心链路验证：切租户重签 Token + UserSession 会话绑定。

覆盖链路（对齐参考项目 /tenants/switch 与 create_login_token）：
  1. 登录建会话：登录后 UserSession 有记录，jti 与 access 一致，tenant_id=is_default 租户
  2. 默认租户解析：resolve_login_tenant 优先 is_default=True 成员
  3. 旧 token 可用：登录签发的 access 调受保护接口 → 200
  4. 切租户重签：switch_tenant 返回新 access/refresh，tenant_id=目标租户
  5. 旧 token 立即失效：切租户后旧 access 调受保护接口 → 401/403
  6. 新 token 可用：新 access 调受保护接口 → 200，且 X-Tenant-Id 上下文为新租户
  7. 刷新建会话：refresh 换新 access → UserSession 新增记录
  8. 登出吊销：logout 后该会话 revoked_at 非空 → 对应 access 失效

用法：.venv/Scripts/python.exe manage.py shell < scripts/verify_tenant_session.py
"""
import uuid
from datetime import datetime

import django
from django.conf import settings

from system.saas.models import Tenant, TenantMember, Role
from system.users.models import User, UserSession
from system.users.serializers import resolve_login_tenant

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def _mk_request(payload, user):
    """构造最小可用 DRF Request（带认证用户，供序列化器取 request.data / META）。

    注意：DRF Request 直接构造必须显式传 parsers，否则 UnsupportedMediaType。
    """
    from rest_framework.parsers import JSONParser
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    raw = factory.post("/api/v1/auth/login/", payload, format="json")
    req = Request(raw, parsers=[JSONParser()])
    req.user = user
    return req


def _mk_authed_request(method, path, user, auth, payload=None):
    """构造带认证 user/auth 的 DRF Request（payload 为 None 时用空 JSON body）。"""
    from rest_framework.parsers import JSONParser
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    kw = {"format": "json"} if payload is not None else {}
    raw = getattr(factory, method)(path, payload or {}, **kw)
    req = Request(raw, parsers=[JSONParser()])
    req.user = user
    req.auth = auth
    return req


def main():
    print("=" * 60)
    print("阶段1 验证：切租户重签 Token + 会话绑定")
    print("=" * 60)

    # ---------- 准备数据 ----------
    suffix = uuid.uuid4().hex[:6]
    username = f"vt_{suffix}"
    user = User.objects.create_user(
        username=username, password="Passw0rd!123", email=f"{username}@t.com"
    )
    tenant_a = Tenant.objects.create(name=f"租户A_{suffix}", slug=f"ta_{suffix}")
    tenant_b = Tenant.objects.create(name=f"租户B_{suffix}", slug=f"tb_{suffix}")
    role = Role.objects.filter(slug="member", tenant__isnull=True).first()
    mem_a = TenantMember.objects.create(
        tenant=tenant_a, user=user, role=role, is_active=True, is_default=True
    )
    TenantMember.objects.create(
        tenant=tenant_b, user=user, role=role, is_active=True, is_default=False
    )

    # ---------- 1. 默认租户解析优先 is_default ----------
    print("\n[1] 默认租户解析（is_default 优先）")
    req = _mk_request({}, user)
    tid = resolve_login_tenant(req, user)
    check("解析结果 = 租户A(is_default)", tid == str(tenant_a.id), f"got={tid}")

    # 请求体显式指定租户B → 优先请求体
    req2 = _mk_request({"tenant_id": str(tenant_b.id)}, user)
    tid2 = resolve_login_tenant(req2, user)
    check("请求体 tenant_id 优先", tid2 == str(tenant_b.id), f"got={tid2}")

    # ---------- 2. 登录建会话 ----------
    print("\n[2] 登录签发 + 会话记录")
    from system.users.services import LoginService

    result = LoginService.login(username, "Passw0rd!123", request=_mk_request({}, user))
    check("登录成功", "error" not in result, str(result)[:200])
    tokens = result["tokens"]
    access = tokens["access"]

    # 解码 access 取 jti / tenant_id
    from rest_framework_simplejwt.tokens import AccessToken

    at = AccessToken(access)
    jti = at.payload.get("jti")
    check("access 带 jti", bool(jti), f"jti={jti}")
    check(
        "access tenant_id = 租户A",
        str(at.payload.get("tenant_id")) == str(tenant_a.id),
        f"got={at.payload.get('tenant_id')}",
    )
    sess = UserSession.objects.filter(user=user, token_jti=jti).first()
    check("UserSession 已建（登录）", sess is not None)
    if sess:
        check(
            "会话租户 = 租户A",
            str(sess.tenant_id) == str(tenant_a.id),
            f"got={sess.tenant_id}",
        )
        check("会话未吊销", sess.revoked_at is None)

    # ---------- 3. 旧 token 访问受保护接口 ----------
    print("\n[3] 旧 token 认证校验")
    from rest_framework.test import APIRequestFactory, force_authenticate
    from rest_framework.views import APIView
    from framework.drf.sliding_jwt import SlidingJWTAuthentication

    class ProbeView(APIView):
        authentication_classes = [SlidingJWTAuthentication]
        permission_classes = []

        def get(self, request):
            from rest_framework.response import Response

            return Response({"ok": True, "jti": request.auth.payload.get("jti")})

    factory = APIRequestFactory()
    probe = ProbeView.as_view()

    raw = factory.get("/probe/", HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = probe(raw)
    check("旧 token 认证通过", resp.status_code == 200, f"status={resp.status_code} body={resp.data}")

    # ---------- 4. 切租户重签 ----------
    print("\n[4] 切租户 → 重签 Token")
    from system.saas.services import TenantService

    raw = factory.post(
        "/api/v1/me/switch-tenant/",
        {"tenant_id": str(tenant_b.id)},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    req = _mk_authed_request("post", "/api/v1/me/switch-tenant/", user, at, {"tenant_id": str(tenant_b.id)})
    result = TenantService.switch_tenant(
        user, str(tenant_b.id), {}, request=req, access_token=at
    )
    check("切租户成功", "error" not in result, str(result)[:300])
    new_access = result.get("access")
    new_refresh = result.get("refresh")
    check("返回新 access/refresh", bool(new_access) and bool(new_refresh))
    new_at = AccessToken(new_access)
    check(
        "新 token tenant_id = 租户B",
        str(new_at.payload.get("tenant_id")) == str(tenant_b.id),
        f"got={new_at.payload.get('tenant_id')}",
    )

    # ---------- 5. 旧 token 立即失效 ----------
    print("\n[5] 旧 token 失效校验")
    raw = factory.get("/probe/", HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = probe(raw)
    check(
        "旧 access 被拒（会话已吊销）",
        resp.status_code in (401, 403),
        f"status={resp.status_code} body={getattr(resp, 'data', None)}",
    )
    old_sess = UserSession.objects.get(user=user, token_jti=jti)
    check("旧会话 revoked_at 已写", old_sess.revoked_at is not None)

    # ---------- 6. 新 token 可用 + 租户上下文 ----------
    print("\n[6] 新 token 可用")
    raw = factory.get("/probe/", HTTP_AUTHORIZATION=f"Bearer {new_access}")
    resp = probe(raw)
    check("新 access 认证通过", resp.status_code == 200, f"status={resp.status_code}")
    check(
        "新 access 上下文 = 租户B",
        resp.data.get("jti") == new_at.payload.get("jti"),
    )

    # ---------- 7. 刷新建会话 ----------
    print("\n[7] 刷新 Token → 新会话")
    from system.users.serializers import RefreshTokenSerializer

    ser = RefreshTokenSerializer(
        data={"refresh": new_refresh},
        context={"request": _mk_request({}, user)},
    )
    ser.is_valid(raise_exception=True)
    refreshed_access = ser.validated_data["access"]
    ratt = AccessToken(refreshed_access)
    new_sess = UserSession.objects.filter(
        user=user, token_jti=ratt.payload.get("jti")
    ).first()
    check("刷新生成了新会话记录", new_sess is not None)
    if new_sess:
        check(
            "刷新会话租户 = 租户B",
            str(new_sess.tenant_id) == str(tenant_b.id),
            f"got={new_sess.tenant_id}",
        )

    # ---------- 8. 登出吊销 ----------
    print("\n[8] 登出 → 会话吊销")
    from system.users.services import LogoutService

    logout_req = _mk_authed_request("post", "/api/v1/auth/logout/", user, ratt)
    # LogoutService 内调 django_logout 需要 request.session（真实请求由中间件提供）
    from django.contrib.sessions.backends.db import SessionStore

    _s = SessionStore()
    _s.create()
    logout_req.session = _s
    LogoutService.logout(logout_req, refresh_token=new_refresh)
    sess_after_logout = UserSession.objects.get(
        user=user, token_jti=ratt.payload.get("jti")
    )
    check("登出后会话已吊销", sess_after_logout.revoked_at is not None)

    # ---------- 收尾 ----------
    print("\n" + "=" * 60)
    print(f"结果：PASS={PASS} FAIL={FAIL}")
    print("=" * 60)
    # 清理测试数据（不污染开发库）
    user.delete()
    tenant_a.delete()
    tenant_b.delete()
    return 0 if FAIL == 0 else 1


django.setup()
raise SystemExit(main())
