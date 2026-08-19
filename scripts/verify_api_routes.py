"""
路由签名校验验证脚本
====================
目的：验证 users 应用下各路由在「生产式签名策略」下的真实行为，
定位哪些路由因为没加进 API_SIGNATURE_EXCLUDE_PATHS 而被 403 拦死。

做法：
  Pass A（静态）：直接用 APISignatureMiddleware 自己的 _should_verify_path 判定，
           不依赖 DB，结果确定。True = 会走签名校验（无签名头必 403）。
  Pass B（实跑）：用 Django 测试客户端真实发请求（不带签名头、不带 token），
           打印真实 HTTP 状态码做交叉验证。
  Pass C（鉴权）：创建用户->登录拿 JWT->带 Bearer 再打一次已排除签名的路由，
           证明「签名排除后只剩 JWT 这一道闸门」。

运行：
  cd /d/Code/djangoProjectTest
  .venv/Scripts/python.exe tmp_route_verify.py
"""
import os
import logging
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.test')
django.setup()

# 压制噪声日志，只保留脚本自身输出
import loguru
loguru.logger.remove()
logging.getLogger('django.request').setLevel(logging.ERROR)
logging.getLogger('django.utils.log').setLevel(logging.ERROR)
logging.getLogger('django.db.backends').setLevel(logging.ERROR)

from django.core.management import call_command
call_command('migrate', run_syncdb=True, verbosity=0, interactive=False)

from django.test import Client
from django.test.utils import override_settings
from framework.api_signature.middleware import APISignatureMiddleware

# 复刻生产签名策略（test.py 默认关掉了签名，这里强制打开以复现真实故障）
SIG_ENABLED = True
INCLUDE = ["/api/*", "/api/v1/*"]
# 直接读 base.py 里的真实排除列表，确保静态判定与线上一致
from django.conf import settings as S
EXCLUDE = list(S.API_SIGNATURE_EXCLUDE_PATHS)

# (方法, 真实完整路径, 路由用途/预期性质)
ROUTES = [
    ("GET",  "/api/users/api/test/",       "TestApiView  GET  (IsAuthenticated)"),
    ("POST", "/api/users/api/test/",       "TestApiView  POST (IsAuthenticated)"),
    ("GET",  "/api/users/system-roles/",   "SystemRoleListView (需登录)"),
    ("POST", "/api/users/register/",       "UserRegisterView (AllowAny)"),
    ("POST", "/api/users/login/",          "UserLoginView (AllowAny)"),
    ("GET",  "/api/users/api/list/",        "UserListView (需登录)"),
    ("POST", "/api/users/logout/",         "UserLogoutView (需登录)"),
    ("GET",  "/api/users/info/",            "UserInfoView (需登录)"),
    ("POST", "/api/users/api/jwt/login/",   "CustomTokenObtainPairView (AllowAny)"),
    ("POST", "/api/users/api/jwt/refresh/", "CustomTokenRefreshView (需 refresh)"),
    ("POST", "/api/users/api/jwt/logout/",  "JWTLogoutView (需登录)"),
    ("POST", "/api/users/api/jwt/verify/",  "VerifyTokenView (需 token)"),
    # v1 挂载镜像（同样的路由，前缀换成 /api/v1/users/）
    ("GET",  "/api/v1/users/api/test/",     "TestApiView @ v1"),
    ("POST", "/api/v1/users/login/",        "UserLoginView @ v1"),
    ("POST", "/api/v1/users/api/jwt/login/", "JWT login @ v1"),
]

print("=" * 100)
print("排除列表（来自 settings.base）:")
for p in EXCLUDE:
    print("   ", p)
print("=" * 100)


def classify(code):
    if code == 403:
        return "❌ 被签名拦死（未加入排除列表）"
    if code == 401:
        return "✅ 过了签名，卡在 JWT 鉴权（符合预期，带 token 即可）"
    if code == 405:
        return "✅ 路由存在，方法不对（签名已放行）"
    if code in (400,):
        return "✅ 已抵达视图，仅参数校验失败（签名已放行）"
    if code in (200, 201):
        return "✅ 完全通过"
    if code == 404:
        return "⚠️ 路径根本不存在（404，检查路由注册）"
    return f"… 其他({code})"


# ---------------------------------------------------------------
# Pass A：静态判定（中间件自身的匹配逻辑）
# ---------------------------------------------------------------
print("\n[Pass A] 静态判定（APISignatureMiddleware._should_verify_path）")
print("-" * 100)
mw = APISignatureMiddleware(get_response=lambda request: None)
mw.enabled = SIG_ENABLED
mw.include_paths = INCLUDE
mw.exclude_paths = EXCLUDE
static_rows = []
for method, path, desc in ROUTES:
    will_verify = mw._should_verify_path(path)  # True=会验签->无签名必 403
    static_rows.append((path, desc, will_verify))
    flag = "会验签(403)" if will_verify else "放行(跳过签名)"
    print(f"  {flag:14s}  {path:42s}  {desc}")

# ---------------------------------------------------------------
# Pass B：实跑（Django 测试客户端，无签名头、无 token）
# ---------------------------------------------------------------
print("\n[Pass B] 实跑（Client，无签名头 / 无 token / Accept=application/json）")
print("-" * 100)

with override_settings(
    API_SIGNATURE_ENABLED=SIG_ENABLED,
    API_SIGNATURE_PATHS=INCLUDE,
    API_SIGNATURE_EXCLUDE_PATHS=EXCLUDE,
):
    client = Client()  # 在 override 作用域内创建 -> 中间件按新配置初始化
    live_rows = []
    for method, path, desc in ROUTES:
        try:
            resp = client.generic(
                method, path,
                HTTP_ACCEPT="application/json",
                content_type="application/json",
            )
            code = resp.status_code
        except Exception as e:  # noqa
            code = f"ERR:{e}"
        live_rows.append((path, desc, code))
        print(f"  {str(code):4s}  {method:4s} {path:42s}  {classify(code)}")

# ---------------------------------------------------------------
# Pass C：鉴权验证（仅对「静态判定为放行」的路由）
# ---------------------------------------------------------------
print("\n[Pass C] 鉴权验证：对已放行签名的路由，带 JWT 再打一次（确认只剩 JWT 闸门）")
print("-" * 100)
with override_settings(
    API_SIGNATURE_ENABLED=SIG_ENABLED,
    API_SIGNATURE_PATHS=INCLUDE,
    API_SIGNATURE_EXCLUDE_PATHS=EXCLUDE,
):
    client = Client(raise_request_exception=False)
    # 建用户（内存库）
    from system.users.models import User
    from system.saas.models import Role
    role, _ = Role.objects.get_or_create(
        name="Verify - 成员", defaults={"slug": "verify-member", "is_active": True}
    )
    u, _ = User.objects.get_or_create(
        username="route_verify_user",
        defaults={"role": role, "email": "rv@example.com"},
    )
    u.set_password("RouteVerify123!")
    u.save()

    # 经已排除签名的 login 拿 token
    r = client.post(
        "/api/users/login/",
        data={"username": "route_verify_user", "password": "RouteVerify123!"},
        content_type="application/json", HTTP_ACCEPT="application/json",
    )
    token = ""
    try:
        token = r.json().get("data", {}).get("access") or r.json().get("access") or ""
    except Exception:
        pass
    print(f"  login 拿 token: HTTP {r.status_code}, token_len={len(token) if token else 0}")

    # 仅验证「静态放行」的代表性路由
    probe = [p for p in ROUTES if not mw._should_verify_path(p[1])]
    for method, path, desc in probe:
        resp = client.generic(
            method, path,
            HTTP_AUTHORIZATION=f"Bearer {token}" if token else "",
            HTTP_ACCEPT="application/json", content_type="application/json",
        )
        print(f"  {resp.status_code:<4}  {method:4s} {path:42s}  {classify(resp.status_code)}")

# ---------------------------------------------------------------
# 汇总：列出需要加入排除列表的真实路径
# ---------------------------------------------------------------
print("\n" + "=" * 100)
print("[汇总] 当前会被签名拦死（需加入 API_SIGNATURE_EXCLUDE_PATHS）的真实路径:")
print("-" * 100)
need = sorted({p for p, d, v in static_rows if v})
if not need:
    print("  （无，全部已放行）")
else:
    for p in need:
        print(f'    "{p}",')
print("=" * 100)
