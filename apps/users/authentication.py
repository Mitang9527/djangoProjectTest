from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from rest_framework.authentication import TokenAuthentication
from rest_framework import exceptions

class ExpiringTokenAuthentication(TokenAuthentication):
    """
    自定义 Token 认证，支持有效期校验
    """
    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed('无效的 Token')

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed('用户已被禁用')

        # 校验有效期
        utc_now = timezone.now()
        if token.created < utc_now - timedelta(hours=settings.TOKEN_EXPIRE_HOURS):
            # 如果过期，可以自动删除旧 Token 并抛出异常
            # token.delete()
            raise exceptions.AuthenticationFailed('Token 已过期，请重新登录')

        return (token.user, token)
