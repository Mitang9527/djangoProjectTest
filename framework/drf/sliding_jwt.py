"""
滑动过期 JWT 认证与中间件。

设计目标
--------
- access token 仍保持固定有效期（TOKEN_EXPIRE_HOURS），到期即失效、可被黑名单吊销。
- 当 access token 剩余有效期低于阈值时，自动签发一个新的 access token，并通过
  响应头 ``X-Access-Token`` 返回给前端；前端检测到该头后更新本地 token，即可实现
  「活跃会话自动续期」——用户无需重新登录，也无需改动登录/刷新流程。

安全与性能约束
--------------
- 仅基于已通过签名验证的 token claims 复制生成新 token，不做任何额外 DB 查询。
- 滑动续期过程中的任何异常都会被吞掉，绝不影响正常认证流程。
- 整体开关由 ``settings.SLIDING_SESSION_ENABLED`` 控制，默认关闭。
"""
from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken

# 滑动续期时需要从旧 token 复制到新 token 的声明（顺序无关）。
# 含 jti：续期的新 access 复用原 jti，与其 UserSession 记录保持一致，
# 保证「切租户吊销会话 → 整条 token 链立即失效」的语义。
_SLIDE_CLAIMS = (jwt_settings.USER_ID_CLAIM, "username", "email", "role_id", "tenant_id", "token_version", "jti")


class SlidingJWTAuthentication(JWTAuthentication):
    """支持滑动过期的 JWT 认证。

    在 SimpleJWT 原生 ``JWTAuthentication`` 基础上，认证成功后判断 access token
    的剩余有效期；若低于阈值且滑动会话已启用，则签发新 access token 并挂载到
    ``request._sliding_access_token``，由 :class:`SlidingTokenMiddleware` 写入响应头。
    """

    def authenticate(self, request: Request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, validated_token = result

        # 令牌版本校验：token_version claim 与用户当前值不一致（重登 / 改密后）
        # 即视为旧 token，立即拒绝。旧 token（部署前签发、无该 claim）留空则跳过，
        # 保证灰度期已登录用户不被强制踢出，直到其自然过期或重新登录。
        expected = getattr(user, "token_version", None)
        actual = validated_token.get("token_version", None)
        if actual is not None and expected is not None and actual != expected:
            raise AuthenticationFailed(
                "该账号已在其他位置登录或密码已修改，请重新登录"
            )

        # jti 会话校验：会话记录存在则强制（切租户 / 登出吊销后旧 token 立即失效）。
        # 记录不存在（存量旧 token / 外部系统）则放行，保证灰度期不踢人。
        # 仅校验 revoked_at：expires_at 由 simplejwt 的 exp claim 负责（滑动续期
        # 复用 jti，会话过期校验会误杀续期后的 token）。
        jti = validated_token.get("jti")
        if jti:
            try:
                from system.users.models import UserSession

                session = UserSession.objects.filter(
                    user=user, token_jti=jti
                ).first()
            except Exception:
                session = None
            if session is not None and session.revoked_at is not None:
                raise AuthenticationFailed(
                    "会话已失效（租户已切换或已登出），请重新登录"
                )

        if not getattr(settings, "SLIDING_SESSION_ENABLED", False):
            return result

        try:
            if "exp" not in validated_token:
                return result
            exp = validated_token["exp"]
            # SimpleJWT 把 exp 存为 int 时间戳（NumericDate），兼容 datetime 形式
            now_ts = timezone.now().timestamp()
            exp_ts = exp.timestamp() if isinstance(exp, datetime) else float(exp)
            remaining = exp_ts - now_ts
            threshold = getattr(settings, "SLIDING_REFRESH_THRESHOLD_SECONDS", 300)
            if remaining < threshold:
                new_token = self._issue_new_access_token(validated_token)
                request._sliding_access_token = str(new_token)
        except Exception:
            # 滑动续期失败绝不影响正常认证
            pass

        return result

    @staticmethod
    def _issue_new_access_token(validated_token) -> AccessToken:
        """基于已验证 token 的声明签发一个新的 access token（无额外 DB 查询）。"""
        new_token = AccessToken()
        for claim in _SLIDE_CLAIMS:
            if claim in validated_token:
                new_token[claim] = validated_token[claim]
        return new_token


class SlidingTokenMiddleware:
    """将滑动续期生成的新 access token 通过响应头返回给前端。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        new_token = getattr(request, "_sliding_access_token", None)
        if new_token:
            response["X-Access-Token"] = new_token
            response["X-Token-Refreshed"] = "true"
        return response
