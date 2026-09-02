"""OIDC 单点登录集成（基于 mozilla-django-oidc 扩展）

设计目标（与用户确认的方案保持一致）：
- 协议：OpenID Connect（标准），可对接任意支持 OIDC 的 IdP
  （Keycloak / Auth0 / Azure AD / 企业微信 / 飞书 等）
- 账号映射：自动建号 + 保留原有账号密码 / JWT 登录作为兜底

关键组件：
- OIDCBackend        : 自定义 Django 认证后端，负责把 IdP 返回的 claims
                       映射到本地 User（按 email / sub 查找或自动创建）。
- OIDCCallbackView   : 回调视图。复用 mozilla 的 token 交换与用户映射，
                       完成 Session 登录后签发 JWT，并通过重定向把 token
                       交给前端 SPA（前端存下后即可用 Bearer 调 API）。
- OIDCLogoutView     : 登出视图，清理本地 Session，可选跳转 IdP 全局登出。

注意：本模块仅在 settings.OIDC_ENABLED 为 True 时才会被 urls 条件导入，
因此 mozilla-django-oidc 未安装 / 未配置时不会触发导入错误。
"""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.views import View

from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView

from loguru import logger

from system.core.audit import record_login_log

User = get_user_model()


class OIDCBackend(OIDCAuthenticationBackend):
    """把 OIDC claims 映射到本地 User。

    映射优先级：email（企业 IdP 通常返回） -> sub（IdP 唯一标识，兜底）。
    自动建号由 settings.OIDC_CREATE_USER 控制（默认开启）。
    """

    def filter_users_by_claims(self, claims):
        email = claims.get("email")
        sub = claims.get("sub")
        if email:
            return User.objects.filter(email__iexact=email)
        if sub:
            # 无 email 时，用 sub 作为用户名查找（需此前已建过号）
            return User.objects.filter(username=sub)
        return User.objects.none()

    def create_user(self, claims):
        email = claims.get("email", "")
        sub = claims.get("sub", "")
        # 用户名来源：email 前缀，否则用 sub
        base = email.split("@")[0] if email else sub
        username = base
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{i}"
            i += 1
        user = User.objects.create_user(
            username=username,
            email=email or "",
            nickname=claims.get("name", username),
        )
        # 按 IdP 角色 claim 绑定本地系统角色（建号时一次，之后每次登录由 update_user 同步）
        self._apply_role_mapping(user, claims)
        logger.info(f"[OIDC] 自动创建用户: username={username}, email={email}")
        return user

    def update_user(self, user, claims):
        changed = False
        name = claims.get("name")
        email = claims.get("email")
        if name and user.nickname != name:
            user.nickname = name
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if changed:
            user.save()
            logger.info(f"[OIDC] 更新用户信息: username={user.username}")
        # 每次登录同步角色（IdP 端角色变更下次登录自动生效）
        if self._apply_role_mapping(user, claims):
            logger.info(f"[OIDC] 同步用户角色: username={user.username}")
        return user

    # ------------------------------------------------------------------
    # 角色映射（OIDC_ROLE_CLAIM + OIDC_ROLE_MAP）
    # ------------------------------------------------------------------

    def _resolve_role_slug(self, claims) -> str | None:
        """
        从 claims 解析出第一个可命中的本地角色 slug。

        规则:
        - 角色取值：claims[OIDC_ROLE_CLAIM]，兼容 str 或 list[str]。
        - 命中链：OIDC_ROLE_MAP 显式映射（IdP 值 → 本地 slug）；
          未在映射表中的值，若与本地系统角色 slug 同名则直通命中。
        - 仅返回本地真实存在的「系统角色」（tenant 为空 且 is_active）的 slug，
          否则返回 None（未命中忽略，不报错）。
        """
        role_claim = getattr(settings, "OIDC_ROLE_CLAIM", "roles")
        role_map = getattr(settings, "OIDC_ROLE_MAP", {}) or {}
        raw = claims.get(role_claim)
        if not raw:
            return None
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        # 延迟导入 Role，避免 oidc 模块 import 时耦合 saas（循环导入风险）
        from system.saas.models import Role

        for value in values:
            if not value:
                continue
            # 显式映射优先；无映射时尝试直通（同名 slug）
            slug = role_map.get(value, value)
            exists = Role.objects.filter(
                tenant__isnull=True, slug=slug, is_active=True
            ).exists()
            if exists:
                return slug
        return None

    def _apply_role_mapping(self, user, claims) -> bool:
        """
        把 IdP 角色绑定到 user.role（单 FK，取第一个命中）。

        Returns: 是否发生变更（绑定/解绑）。未命中且用户本无角色时返回 False。
        """
        from system.saas.models import Role

        slug = self._resolve_role_slug(claims)
        role = None
        if slug:
            role = Role.objects.filter(tenant__isnull=True, slug=slug, is_active=True).first()
        if user.role_id != (role.id if role else None):
            user.role = role
            user.save(update_fields=["role"])
            return True
        return False


class OIDCCallbackView(OIDCAuthenticationCallbackView):
    """OIDC 回调视图。

    复用父类完整的授权码交换 + 用户映射流程（login_success 完成 Session 登录），
    通过重写 success_url，在登录成功后签发 JWT（access + refresh），
    并把它通过重定向 query string 交给前端 SPA（前端存下后即可用 Bearer 调 API）。
    """

    @property
    def success_url(self):
        # 登录成功后 self.user 已就绪，签发 JWT（仅签发一次，避免重复访问时多次签发）
        if not hasattr(self, "_oidc_jwt"):
            from rest_framework_simplejwt.tokens import RefreshToken

            user = getattr(self, "user", None)
            if user is None:
                return getattr(settings, "OIDC_LOGOUT_REDIRECT_URL", "/")
            refresh = RefreshToken.for_user(user)
            # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
            if hasattr(user, "token_version"):
                user.token_version = (user.token_version or 0) + 1
                user.save(update_fields=["token_version"])
                refresh["token_version"] = user.token_version
            # 多租户上下文 claim：写入默认租户（OIDC 回调无显式 tenant_id，
            # 取用户 is_default / 首个活跃租户成员关系；无成员关系则不写）。
            from system.users.serializers import attach_tenant_claim, create_user_session

            attach_tenant_claim(refresh, getattr(self, "request", None), user)
            # 先取 access 实例复用（属性每次访问生成新 jti，否则会话 jti 与 access 不一致）
            access = refresh.access_token
            # 写入会话记录（jti 绑定 user+tenant）：切租户 / 登出吊销后旧 access 立即失效
            create_user_session(
                user, access,
                refresh.payload.get("tenant_id"),
                getattr(self, "request", None),
                notify_new_device=True,
            )
            # 租户级登录日志（成功）
            record_login_log(
                email=user.email or user.username, status='success',
                user=user,
                tenant_id=refresh.payload.get("tenant_id"),
                request=getattr(self, "request", None),
            )
            self._oidc_jwt = {
                "access": str(access),
                "refresh": str(refresh),
            }
        base = getattr(settings, "OIDC_FRONTEND_REDIRECT_URL", "") or "/"
        return f"{base}?{urlencode(self._oidc_jwt)}"


class OIDCLogoutView(View):
    """OIDC 登出。

    清理本地 Session；若配置了 IdP 登出端点，则重定向到 IdP 全局登出，
    登出后跳回 OIDC_LOGOUT_REDIRECT_URL。
    """

    def get(self, request):
        from django.contrib.auth import logout as django_logout

        django_logout(request)
        logout_ep = getattr(settings, "OIDC_OP_LOGOUT_ENDPOINT", "")
        if logout_ep:
            redirect_uri = request.build_absolute_uri(
                getattr(settings, "OIDC_LOGOUT_REDIRECT_URL", "/")
            )
            return redirect(
                f"{logout_ep}?{urlencode({'post_logout_redirect_uri': redirect_uri})}"
            )
        return redirect(getattr(settings, "OIDC_LOGOUT_REDIRECT_URL", "/"))
