import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class CustomUserManager(UserManager):
    """自定义用户管理器"""
    pass

class User(AbstractUser):
    """自定义用户模型"""
    nickname = models.CharField(max_length=50, blank=True, verbose_name='昵称')
    mobile = models.CharField(max_length=11, unique=True, null=True, blank=True, verbose_name='手机号')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True, verbose_name='头像')
    role = models.ForeignKey(
        'saas.Role', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='users', verbose_name='系统角色'
    )
    # 令牌版本戳：每次登录 / 改密自增，使该用户所有旧 JWT 立即失效（重登即废全部旧 token）
    token_version = models.PositiveIntegerField(default=0, verbose_name='令牌版本')

    objects = CustomUserManager()

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        ordering = ['-id']

    def __str__(self):
        return self.username


class UserSession(models.Model):
    """
    JWT 会话表（效仿参考项目的会话-租户绑定模型）。

    每次签发 access token 时记录一条会话：token_jti 绑定 user + tenant。
    用途：
      - 切换租户时吊销旧会话并重签新 token（旧 token 立即失效）；
      - 认证层可选校验 token 的 jti/tenant 与会话记录一致（记录存在则强制）。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='sessions', verbose_name='用户',
    )
    tenant = models.ForeignKey(
        'saas.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='sessions', verbose_name='租户',
    )
    token_jti = models.CharField('Token JTI', max_length=64, db_index=True)
    ip = models.CharField('IP', max_length=64, blank=True)
    user_agent = models.CharField('User-Agent', max_length=512, blank=True)
    expires_at = models.DateTimeField('过期时间')
    revoked_at = models.DateTimeField('吊销时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '用户会话'
        verbose_name_plural = '用户会话'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'token_jti']),
            models.Index(fields=['user', 'revoked_at']),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.tenant_id} jti={self.token_jti}"
