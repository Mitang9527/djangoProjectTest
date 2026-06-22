from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from rest_framework.authtoken.models import Token

class CustomUserManager(UserManager):
    """自定义用户管理器，确保创建超级用户时角色为 admin"""
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        return super().create_superuser(username, email, password, **extra_fields)

class User(AbstractUser):
    """自定义用户模型"""
    ROLE_CHOICES = (
        ('admin', '管理员'),
        ('user', '普通用户'),
    )
    nickname = models.CharField(max_length=50, blank=True, verbose_name='昵称')
    mobile = models.CharField(max_length=11, unique=True, null=True, blank=True, verbose_name='手机号')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True, verbose_name='头像')
    token = models.CharField(max_length=255, null=True, blank=True, verbose_name='Token')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='user', verbose_name='角色')

    objects = CustomUserManager()

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        ordering = ['-id']

    def __str__(self):
        return self.username

# @receiver(user_logged_in)
# def on_user_logged_in(sender, request, user, **kwargs):
#     """
#     当用户登录成功时，自动获取或创建 Token 并记录到用户表
#     支持：Admin登录、API登录、Session登录等所有方式
#     （已禁用，改用 JWT 认证）
#     """
#     token, created = Token.objects.get_or_create(user=user)
#     user.token = token.key
#     user.save(update_fields=['token'])
