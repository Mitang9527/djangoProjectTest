"""
演示 authentication_classes 在 ping 接口上的作用（对照测试）。

两个视图：
- PingView       : authentication_classes = []  （DRF 层完全不做认证）
- PingAuthView   : authentication_classes = [SlidingJWTAuthentication]

两者都 permissions.AllowAny，故「无 token」都能 200；
区别只在 DRF 是否会去解析请求里的凭证。
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken

from system.core.views import PingView, PingAuthView

User = get_user_model()
factory = APIRequestFactory()


def _call(view_cls, token=None):
    req = factory.get("/api/v1/core/ping/")
    if token:
        req.META["HTTP_AUTHORIZATION"] = token
    try:
        resp = view_cls.as_view()(req)
        # 响应经 CustomRenderer 信封包装：视图原始字典位于 resp.data["data"] 下
        raw = resp.data if isinstance(resp.data, dict) else {}
        payload = raw.get("data", raw)
        d = payload.get("auth_demo", {}) if isinstance(payload, dict) else {}
        return resp.status_code, d
    except Exception as e:
        return getattr(e, "status_code", 500), {"error": f"{type(e).__name__}: {e}"}


@pytest.fixture
def jwt_token(db):
    u, _ = User.objects.get_or_create(username="demo_auth_user")
    return str(RefreshToken.for_user(u).access_token), u.username


def test_ping_auth_classes_demo(jwt_token):
    token, username = jwt_token
    bad = "Bearer not.a.real.token"

    # ---- PingView: authentication_classes = [] ----
    s1, d1 = _call(PingView)                       # 无 token
    s2, d2 = _call(PingView, f"Bearer {token}")    # 有效 JWT
    s3, d3 = _call(PingView, bad)                  # 伪造 JWT

    # ---- PingAuthView: authentication_classes = [SlidingJWTAuthentication] ----
    s4, d4 = _call(PingAuthView)                   # 无 token
    s5, d5 = _call(PingAuthView, f"Bearer {token}")  # 有效 JWT
    s6, d6 = _call(PingAuthView, bad)              # 伪造 JWT

    print("\n" + "=" * 72)
    print("PingView  ->  authentication_classes = []  (DRF 层不做任何认证)")
    print("=" * 72)
    print(f"  无 token   : HTTP {s1} | user={d1.get('user')} is_auth={d1.get('is_authenticated')} auth={d1.get('auth')}")
    print(f"  有效 JWT   : HTTP {s2} | user={d2.get('user')} is_auth={d2.get('is_authenticated')} auth={d2.get('auth')}")
    print(f"  伪造 JWT   : HTTP {s3} | {d3}")
    print()
    print("PingAuthView -> authentication_classes = [SlidingJWTAuthentication]")
    print("=" * 72)
    print(f"  无 token   : HTTP {s4} | user={d4.get('user')} is_auth={d4.get('is_authenticated')} auth={d4.get('auth')}")
    print(f"  有效 JWT   : HTTP {s5} | user={d5.get('user')} is_auth={d5.get('is_authenticated')} auth={d5.get('auth')}")
    print(f"  伪造 JWT   : HTTP {s6} | {d6}")
    print("=" * 72)

    # 断言：PingView 用 authentication_classes=[]，根本不解析身份，响应里不含 auth_demo；
    #       PingAuthView 用 JWT 后端，无 token 仍匿名(AllowAny)、有效 token 识别用户、伪造 token 拒绝
    assert "auth_demo" not in d1                      # [] 不暴露任何身份解析结果
    assert "auth_demo" not in d2                      # [] 忽略任何 token
    assert d4.get("user") == "AnonymousUser"          # 无 token 仍匿名(AllowAny)
    assert d5.get("user") == username                 # 有效 JWT 填充 user
    assert s6 == 401                                  # 伪造 JWT 被认证层拒绝
