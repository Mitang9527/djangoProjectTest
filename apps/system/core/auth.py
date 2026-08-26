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

        if not getattr(settings, "ALLOW_DEMO_LOGIN", False):
            logger.warning(
                f"[DEMO-LOGIN] 禁用状态尝试登录 username={request.data.get('username')} ip={ip}"
            )
            return Response(
                {"detail": "演示登录已禁用，请使用正式登录方式（注册 / OIDC SSO）"},
                status=status.HTTP_403_FORBIDDEN,
            )
        username = (request.data.get('username') or '').strip()
        if not username:
            logger.info(f"[DEMO-LOGIN] 用户名为空 ip={ip}")
            return Response({'detail': '请输入用户名'}, status=status.HTTP_400_BAD_REQUEST)

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
        logger.info(
            f"[DEMO-LOGIN] 登录成功 user_id={user.id} username={user.username} "
            f"new_created={created} is_staff={user.is_staff} ip={ip}"
        )
        data = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            },
        }
        if quota is not None:
            data['quota'] = quota
        return Response(data)
