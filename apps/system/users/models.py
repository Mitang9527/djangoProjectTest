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
