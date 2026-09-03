"""用户域数据模型。

核心模型：
- User          自定义用户（继承 AbstractUser，扩展昵称/手机号/头像/角色/令牌版本）
- UserSession   用户会话记录（多端登录、设备识别、踢下线）
- OAuthProvider 第三方 OAuth 提供商配置
- OAuthAccount  第三方账号绑定关系
"""

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from framework.security.sensitive import SensitiveField


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

    # ── MFA TOTP 双因子认证（对齐 Fast-Vben-Admin core/mfa.py）──
    # mfa_secret_encrypted：Fernet 加密后的 TOTP secret（见 framework/security/mfa.py）
    # mfa_recovery_code_hashes：恢复码 HMAC-SHA256 哈希列表 JSON（明文仅绑定/重置时展示一次）
    mfa_enabled = models.BooleanField(default=False, verbose_name='MFA 已启用')
    mfa_secret_encrypted = models.CharField(max_length=500, null=True, blank=True, verbose_name='MFA 密钥(加密)')
    mfa_confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='MFA 确认时间')
    mfa_recovery_code_hashes = models.TextField(null=True, blank=True, verbose_name='MFA 恢复码哈希')

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


class OAuthProvider(models.Model):
    """OAuth2 第三方登录提供方配置（平台级，管理端维护）。

    支持任意标准 OAuth2 Authorization Code + PKCE 提供方
    （GitHub / Google / 微信开放平台 等）。client_secret 仅在后端
    换取 token 时使用，绝不返回前端。
    """

    name = models.SlugField('提供方标识', max_length=50, unique=True)
    display_name = models.CharField('显示名称', max_length=100, blank=True)
    client_id = models.CharField('Client ID', max_length=255)
    # SensitiveField：落库为版本化 Fernet 密文（v1:...），读库自动解密。
    # 仅后端换取 token 时读取，绝不回显前端；密文不可见故不可用于查询/排序/唯一约束。
    client_secret = SensitiveField('Client Secret', max_length=255)
    authorize_url = models.URLField('授权端点', max_length=500)
    token_url = models.URLField('Token 端点', max_length=500)
    userinfo_url = models.URLField('用户信息端点', max_length=500)
    scope = models.CharField('Scope', max_length=255, blank=True,
                             help_text='授权范围，如 "read:user user:email"；留空则不传 scope 参数')
    redirect_uri = models.CharField('回调地址', max_length=500, blank=True,
                                    help_text='留空则按当前请求动态生成（/api/v1/users/oauth/{name}/callback/）')
    pkce_enabled = models.BooleanField('启用 PKCE', default=True,
                                       help_text='授权码模式强制 PKCE（S256），防止授权码截获重放')
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'OAuth2 提供方'
        verbose_name_plural = 'OAuth2 提供方'
        ordering = ['name']

    def __str__(self):
        return self.display_name or self.name


class OAuthAccount(models.Model):
    """用户与第三方 OAuth2 账号的绑定关系。

    (provider, provider_uid) 唯一：同一第三方账号只能绑定一个本地用户。
    email 冗余存储便于按邮箱匹配既有账号（OAUTH2_AUTO_BIND_EMAIL）。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='oauth_accounts', verbose_name='用户',
    )
    provider = models.ForeignKey(
        OAuthProvider, on_delete=models.CASCADE,
        related_name='accounts', verbose_name='提供方',
    )
    provider_uid = models.CharField('第三方唯一标识', max_length=255)
    email = models.EmailField('第三方邮箱', max_length=255, blank=True)
    extra_data = models.JSONField('原始资料', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'OAuth2 绑定'
        verbose_name_plural = 'OAuth2 绑定'
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_uid'],
                name='uniq_oauth_provider_uid',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'provider']),
        ]

    def __str__(self):
        return f"{self.user.username} <- {self.provider.name}:{self.provider_uid}"
