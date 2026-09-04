"""全局演示登录（前后端联调用）

- 与业务模块解耦：core 不反向依赖 business.ai_studio，额度在「已安装时」懒初始化；
- 生产环境必须设置 ALLOW_DEMO_LOGIN=False 关闭，否则任意用户名可签发 JWT；
- 路由由 system.core.urls 注册为 /api/demo-login/，对全项目生效。
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from loguru import logger

from system.core.audit import record_login_log
from framework.gateway.login_throttle import LoginThrottleService

User = get_user_model()


def _client_ip(request) -> str:
    """取客户端 IP，兼容反向代理（X-Forwarded-For 取第一个）。"""
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    if ',' in ip:
        ip = ip.split(',')[0].strip()
    return ip


def _maybe_quota(user):
    """懒初始化业务额度（ai_studio 已安装时），避免 core 反向依赖 business。

    返回 {'balance', 'frozen'} 或 None（未安装/出错）。
    """
    try:
        from business.ai_studio.services import get_or_create_quota
    except Exception:
        return None
    try:
        quota = get_or_create_quota(user)
        return {'balance': quota.balance, 'frozen': quota.frozen}
    except Exception:
        return None


class DemoLoginView(APIView):
    """全局演示登录：查找/创建用户并签发 JWT，便于前后端联调。

    默认禁用，需 ALLOW_DEMO_LOGIN=True 才启用。生产环境请改用正式注册 + OIDC SSO。
    """

    permission_classes = [AllowAny]

    def post(self, request):
        ip = _client_ip(request)

        if not getattr(settings,"ALLOW_DEMO_LOGIN", False):
            logger.warning(
                f"[DEMO-LOGIN] 禁用状态尝试登录 username={request.data.get('username')} ip={ip}"
            )
            record_login_log(
                email=(request.data.get('username') or '').strip(),
                status='failed', request=request,
                failure_reason='demo_login_disabled',
            )
            return Response(
                {"detail": "演示登录已禁用，请使用正式登录方式（注册 / OIDC SSO）"},
                status=status.HTTP_403_FORBIDDEN,
            )

        username = (request.data.get('username') or '').strip()

        if not username:
            logger.info(f"[DEMO-LOGIN] 用户名为空 ip={ip}")
            record_login_log(email='', status='failed', request=request,
                             failure_reason='empty_username')
            return Response(
                {"detail": "请输入用户名"}, status=status.HTTP_400_BAD_REQUEST)

        # 登录限流预检：演示登录同样受 IP / 用户名双维度保护（防暴力刷账号）
        if LoginThrottleService.is_login_rate_limited(request, username):
            logger.warning(f"[DEMO-LOGIN] 触发登录限流 username={username} ip={ip}")
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='rate_limited')
            return Response({"detail": "尝试过于频繁，请稍后再试"},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        user, created = User.objects.get_or_create(username=username)
        if not user.email and '@' in username:
            user.email = username
            user.save(update_fields=['email'])

        quota = _maybe_quota(user)
        refresh = RefreshToken.for_user(user)
        # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
        if hasattr(user, "token_version"):
            user.token_version = (user.token_version or 0) + 1
            user.save(update_fields=["token_version"])
            refresh["token_version"] = user.token_version
        # 多租户上下文 claim：写入默认租户（请求体 tenant_id 优先，否则 is_default 成员）
        from system.users.serializers import attach_tenant_claim, create_user_session

        tenant_id = attach_tenant_claim(refresh, request, user)
        # 先取 access 实例复用（属性每次访问生成新 jti，否则会话 jti 与 access 不一致）
        access = refresh.access_token
        # 写入会话记录（jti 绑定 user+tenant）：切租户 / 登出吊销后旧 access 立即失效
        create_user_session(user, access, tenant_id, request, notify_new_device=True)
        logger.info(
            f"[DEMO-LOGIN] 登录成功 user_id={user.id} username={user.username} "
            f"new_created={created} is_staff={user.is_staff} ip={ip}"
        )
        # 租户级登录日志（成功）
        record_login_log(
            email=user.email or user.username, status='success',
            user=user, tenant_id=tenant_id, request=request,
        )
        # 登录成功清零 IP / 用户名双维度计数与锁定
        LoginThrottleService.clear_failed_login_attempts(request, username)
        data = {
            'access': str(access),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'tenant_id': tenant_id,
            },
        }
        if quota is not None:
            data['quota'] = quota
        return Response(data)
