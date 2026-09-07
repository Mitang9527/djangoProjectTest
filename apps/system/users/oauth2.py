"""OAuth2 第三方登录（Authorization Code + PKCE）。
端点：GET authorize/（匿名生成授权链接）→ 第三方回跳 callback?code&state（匿名换 token→拉 userinfo→匹配/建号→签发 JWT）；已登录 POST bind/ 绑定账号。
安全：PKCE S256（code_verifier 仅后端，防重放）；state 一次性消费（Lua GETDEL，防 CSRF/授权码注入）；client_secret 不出后端；自动建号/email 绑定由 OAUTH2_AUTO_CREATE_USER/OAUTH2_AUTO_BIND_EMAIL 控制；签发走 issue_login_tokens（token_version+租户 claim+会话+新设备提醒+登录日志）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import pickle
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from loguru import logger


class OAuth2Error(Exception):
    """OAuth2 业务错误（携带 HTTP 状态码与错误码）"""

    def __init__(self, message: str, status_code: int = 400, code: str = "oauth2_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def _ensure_http_url(url: str) -> None:
    """校验 provider 端点 scheme。

    端点 URL 取自后台配置的 provider 字段（token_url / userinfo_url），虽然不是终端
    用户输入，但仍需挡掉 ``file://``、``ftp://`` 等非 HTTP scheme，避免配置被篡改后
    演变为 SSRF 或本地文件读取。
    """
    if urllib.parse.urlparse(url or "").scheme not in ("http", "https"):
        logger.warning(f"[OAuth2] 非法的 provider 端点: {url}")
        raise OAuth2Error("第三方服务地址非法", 400, "provider_bad_url")


_GETDEL_SCRIPT = """
local v = redis.call('GET', KEYS[1])
if v then
    redis.call('DEL', KEYS[1])
end
return v
"""


class OAuth2Service:
    """OAuth2 授权码 + PKCE 状态机（state 存 Redis，一次性消费）"""

    KEY_PREFIX = "oauth2:state"

    # Redis 可用性（对齐 QRLoginService）

    @staticmethod
    def _client():
        from framework.cache.redis_client import get_redis

        return get_redis()

    @classmethod
    def _redis_ready(cls) -> bool:
        """Redis 真实可用（_NullRedis.ping 返回 False 而非抛异常）"""
        try:
            return bool(cls._client().get_client().ping())
        except Exception:
            return False

    # 授权链接构造（authorize）

    @classmethod
    def build_authorize(cls, provider_name: str, request) -> dict:
        """前端获取第三方授权链接（匿名）。Returns: {"authorize_url","state","expires_in"}"""
        provider = cls._get_provider(provider_name)
        if not cls._redis_ready():
            raise OAuth2Error(
                "OAuth2 登录依赖 Redis，当前服务不可用", 503, "redis_unavailable"
            )
        code_verifier, code_challenge = cls._generate_pkce()
        state = uuid.uuid4().hex
        payload = {"provider": provider.name, "code_verifier": code_verifier}
        ok = cls._client().set(cls._key(state), payload, ex=cls._state_ttl())
        if not ok:
            raise OAuth2Error("创建授权请求失败，请重试", 500, "state_create_failed")

        params = {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": cls._redirect_uri(provider, request),
            "state": state,
        }
        if provider.scope:
            params["scope"] = provider.scope
        if provider.pkce_enabled:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        authorize_url = f"{provider.authorize_url}?{urllib.parse.urlencode(params)}"
        logger.info(f"[OAuth2] 生成授权链接: provider={provider.name}, state={state}")
        return {
            "authorize_url": authorize_url,
            "state": state,
            "expires_in": cls._state_ttl(),
        }

    # 回调处理（callback）

    @classmethod
    def handle_callback(cls, provider_name: str, code: str, state: str, request) -> dict:
        """第三方授权后回跳处理（匿名）：换 token→拉 userinfo→匹配/建号→签发 JWT。Returns: {"access","refresh","is_new_user","user"}"""
        provider = cls._get_provider(provider_name)
        if not code:
            raise OAuth2Error("缺少授权码 code", 400, "missing_code")
        if not state:
            raise OAuth2Error("缺少 state", 400, "missing_state")
        if not cls._redis_ready():
            raise OAuth2Error(
                "OAuth2 登录依赖 Redis，当前服务不可用", 503, "redis_unavailable"
            )

        # state 一次性消费（Lua GETDEL 原子，防并发复用/CSRF 注入）
        raw = cls._lua_getdel(cls._key(state))
        if raw is None:
            raise OAuth2Error("state 无效或已过期，请重新发起登录", 400, "invalid_state")
        if raw.get("provider") != provider.name:
            raise OAuth2Error("state 与提供方不匹配", 400, "state_provider_mismatch")
        code_verifier = raw.get("code_verifier") or ""

        # code+PKCE 换 token（client_secret 仅在此使用，不出后端）
        redirect_uri = cls._redirect_uri(provider, request)
        token_data = cls._exchange_token(provider, code, redirect_uri, code_verifier)
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuth2Error("换取访问令牌失败", 502, "token_exchange_failed")

        profile = cls._fetch_userinfo(provider, access_token)

        # 匹配/绑定/建号
        user, is_new_user = cls._resolve_user(provider, profile)

        # 统一签发链 issue_login_tokens（token_version+租户 claim+会话+新设备提醒+登录日志）
        from system.users.serializers import issue_login_tokens

        tokens = issue_login_tokens(user, request, notify_new_device=True)
        logger.info(
            f"[OAuth2] 登录成功: provider={provider.name}, user={user.username}, "
            f"new_user={is_new_user}"
        )
        return {
            **tokens,
            "is_new_user": is_new_user,
            "user": {
                "id": user.pk,
                "username": user.username,
                "nickname": user.nickname,
                "email": user.email,
            },
        }

    # 绑定（bind，已登录用户）

    @classmethod
    def bind_account(cls, user, provider_name: str, code: str, state: str, request) -> dict:
        """已登录用户把第三方账号绑定到当前用户（JWT 鉴权）。"""
        provider = cls._get_provider(provider_name)
        if not code or not state:
            raise OAuth2Error("缺少 code 或 state", 400, "missing_params")
        if not cls._redis_ready():
            raise OAuth2Error(
                "OAuth2 登录依赖 Redis，当前服务不可用", 503, "redis_unavailable"
            )
        raw = cls._lua_getdel(cls._key(state))
        if raw is None:
            raise OAuth2Error("state 无效或已过期，请重新发起", 400, "invalid_state")
        if raw.get("provider") != provider.name:
            raise OAuth2Error("state 与提供方不匹配", 400, "state_provider_mismatch")

        token_data = cls._exchange_token(
            provider, code, cls._redirect_uri(provider, request),
            raw.get("code_verifier") or "",
        )
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuth2Error("换取访问令牌失败", 502, "token_exchange_failed")
        profile = cls._fetch_userinfo(provider, access_token)

        from system.users.models import OAuthAccount

        uid = cls._profile_uid(profile)
        existing = OAuthAccount.objects.filter(provider=provider, provider_uid=uid).first()
        if existing and existing.user_id != user.pk:
            raise OAuth2Error(
                "该第三方账号已绑定其他用户", 409, "account_already_bound"
            )
        account, created = OAuthAccount.objects.update_or_create(
            provider=provider, provider_uid=uid,
            defaults={
                "user": user,
                "email": (profile.get("email") or "").strip().lower(),
                "extra_data": profile or {},
            },
        )
        logger.info(
            f"[OAuth2] 绑定账号: user={user.username}, provider={provider.name}, "
            f"uid={uid}, created={created}"
        )
        return {"bound": True, "created": created, "provider": provider.name}

    # 内部

    @classmethod
    def _key(cls, state: str) -> str:
        return f"{cls.KEY_PREFIX}:{state}"

    @classmethod
    def _state_ttl(cls) -> int:
        return int(getattr(settings, "OAUTH2_STATE_TTL", 600) or 600)

    @classmethod
    def _get_provider(cls, name: str):
        from system.users.models import OAuthProvider

        provider = OAuthProvider.objects.filter(name=name, is_active=True).first()
        if provider is None:
            raise OAuth2Error("该第三方登录未启用或不存在", 404, "provider_not_found")
        return provider

    @classmethod
    def _redirect_uri(cls, provider, request) -> str:
        """回调地址：优先表配置；否则按当前请求动态生成。"""
        if provider.redirect_uri:
            return provider.redirect_uri
        if request is None:
            return ""
        return request.build_absolute_uri(
            f"/api/v1/users/oauth/{provider.name}/callback/"
        )

    @staticmethod
    def _generate_pkce() -> tuple[str, str]:
        """生成 PKCE 对。verifier 43 字符（S256 兼容），challenge 为 SHA-256 base64url。"""
        code_verifier = secrets.token_urlsafe(32)  # 43 chars, [A-Za-z0-9_-]
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = (
            base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )
        return code_verifier, code_challenge

    @classmethod
    def _lua_getdel(cls, key: str):
        """原子 GET+DEL。返回 pickle 反序列化后的 dict；键不存在/异常返回 None。"""
        try:
            raw = cls._client().get_client().eval(_GETDEL_SCRIPT, 1, key)
        except Exception:
            return None
        if raw is None or raw == 0:
            return None
        try:
            return pickle.loads(raw)  # nosec B301  # 仅反序列化本服务自己写入 Redis 的数据
        except Exception:
            return None

    # HTTP 调用（标准库 urllib，零新依赖）

    @staticmethod
    def _http_post_form(url: str, data: dict) -> dict:
        _ensure_http_url(url)
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")
        try:
            # scheme 已由 _ensure_http_url() 限制为 http/https
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            logger.warning(f"[OAuth2] token 交换 HTTP {e.code}: {url}")
            raise OAuth2Error(
                "第三方授权服务返回错误", 502, "provider_http_error"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning(f"[OAuth2] token 交换网络错误: {url}: {e}")
            raise OAuth2Error(
                "第三方授权服务暂不可达", 502, "provider_unreachable"
            ) from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"[OAuth2] token 交换响应解析失败: {url}: {e}")
            raise OAuth2Error(
                "第三方授权服务响应异常", 502, "provider_bad_response"
            ) from e

    @staticmethod
    def _http_get_json(url: str, headers: dict | None = None) -> dict:
        _ensure_http_url(url)
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            # scheme 已由 _ensure_http_url() 限制为 http/https
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            logger.warning(f"[OAuth2] userinfo HTTP {e.code}: {url}")
            raise OAuth2Error(
                "获取第三方用户信息失败", 502, "provider_http_error"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning(f"[OAuth2] userinfo 网络错误: {url}: {e}")
            raise OAuth2Error(
                "第三方授权服务暂不可达", 502, "provider_unreachable"
            ) from e
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"[OAuth2] userinfo 解析失败: {url}: {e}")
            raise OAuth2Error(
                "第三方授权服务响应异常", 502, "provider_bad_response"
            ) from e

    @classmethod
    def _exchange_token(cls, provider, code: str, redirect_uri: str,
                        code_verifier: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
            "redirect_uri": redirect_uri,
        }
        if provider.pkce_enabled:
            data["code_verifier"] = code_verifier
        return cls._http_post_form(provider.token_url, data)

    @classmethod
    def _fetch_userinfo(cls, provider, access_token: str) -> dict:
        return cls._http_get_json(
            provider.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    @staticmethod
    def _profile_uid(profile: dict) -> str:
        uid = profile.get("id") if profile else None
        if uid is None:
            uid = profile.get("sub") if profile else None
        return str(uid or "").strip()

    @classmethod
    def _resolve_user(cls, provider, profile: dict):
        """第三方用户→本地用户，返回 (user, is_new_user)。
        规则：1)已有绑定→该用户（更新冗余信息）；2)email 命中本地用户（OAUTH2_AUTO_BIND_EMAIL 默认开）→绑定；
        3)OAUTH2_AUTO_CREATE_USER（默认开）→自动建号（用户名冲突 +i）。
        """
        from system.users.models import OAuthAccount, User

        uid = cls._profile_uid(profile)
        if not uid:
            raise OAuth2Error(
                "第三方返回的用户标识缺失", 502, "invalid_userinfo"
            )
        email = (profile.get("email") or "").strip().lower()

        account = OAuthAccount.objects.filter(
            provider=provider, provider_uid=uid
        ).first()
        if account:
            changed = False
            if email and account.email != email:
                account.email = email
                changed = True
            if profile and account.extra_data != profile:
                account.extra_data = profile
                changed = True
            if changed:
                account.save()
            return account.user, False

        user = None
        is_new_user = False
        if email and getattr(settings, "OAUTH2_AUTO_BIND_EMAIL", True):
            user = User.objects.filter(email__iexact=email).first()
        if user is None and getattr(settings, "OAUTH2_AUTO_CREATE_USER", True):
            user = cls._auto_create_user(profile, email, uid)
            is_new_user = True
        if user is None:
            raise OAuth2Error(
                "该第三方账号未绑定本地用户，请先登录账号后在个人中心绑定",
                400, "unbound_account",
            )
        OAuthAccount.objects.create(
            user=user, provider=provider, provider_uid=uid,
            email=email, extra_data=profile or {},
        )
        return user, is_new_user

    @staticmethod
    def _auto_create_user(profile: dict, email: str, uid: str):
        """自动建号（对齐 OIDCBackend.create_user：email 前缀优先，冲突 +i）。"""
        from system.users.models import User

        # 用户名来源：email 前缀优先，否则 name，最后 uid
        base = email.split("@")[0] if email else (
            (profile.get("name") or "").strip() or uid
        )
        username = base
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{i}"
            i += 1
        user = User.objects.create_user(
            username=username,
            email=email or "",
            nickname=profile.get("name") or username,
        )
        logger.info(f"[OAuth2] 自动创建用户: username={username}, email={email}")
        return user


# 视图

class OAuth2AuthorizeView(APIView):
    """获取第三方授权链接（匿名）"""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, provider):
        try:
            data = OAuth2Service.build_authorize(provider, request)
        except OAuth2Error as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status_code)
        return Response(data)


class OAuth2CallbackView(APIView):
    """第三方授权回跳（匿名）：换 token→拉 userinfo→匹配/建号→签发 JWT。
    配置 OAUTH2_FRONTEND_REDIRECT_URL 时 302 重定向前端携带 token（对齐 OIDC），否则返回 JSON 供前端 fetch 处理。
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, provider):
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        error = request.query_params.get("error", "")
        if error:
            return Response(
                {"detail": f"第三方授权被拒绝: {error}", "code": "provider_denied"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data = OAuth2Service.handle_callback(provider, code, state, request)
        except OAuth2Error as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status_code)

        frontend_url = getattr(settings, "OAUTH2_FRONTEND_REDIRECT_URL", "") or ""
        if frontend_url:
            from django.http import HttpResponseRedirect

            query = urllib.parse.urlencode(
                {"access": data["access"], "refresh": data["refresh"]}
            )
            return HttpResponseRedirect(f"{frontend_url}?{query}")
        return Response(data)


class OAuth2BindView(APIView):
    """已登录用户绑定第三方账号（JWT 鉴权）"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, provider):
        code = request.data.get("code", "")
        state = request.data.get("state", "")
        try:
            data = OAuth2Service.bind_account(
                request.user, provider, code, state, request
            )
        except OAuth2Error as e:
            return Response({"detail": e.message, "code": e.code}, status=e.status_code)
        return Response(data)
