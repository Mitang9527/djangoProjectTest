"""
SaaS 后台管理系统 - 数据库模型
"""
import re
import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class Plan(models.Model):
    """
    套餐表
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', _('启用')
        INACTIVE = 'inactive', _('禁用')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('名称'), max_length=100)
    slug = models.SlugField(_('标识'), unique=True, max_length=100)
    description = models.TextField(_('描述'), blank=True)
    price = models.DecimalField(_('月价格'), max_digits=10, decimal_places=2)
    price_yearly = models.DecimalField(_('年价格'), max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(_('货币'), max_length=10, default='CNY')
    max_users = models.IntegerField(_('最大用户数'), default=10)
    max_storage_mb = models.IntegerField(_('最大存储(MB)'), default=1024)
    is_active = models.BooleanField(_('是否启用'), default=True)
    is_featured = models.BooleanField(_('是否推荐'), default=False)
    sort_order = models.IntegerField(_('排序'), default=0)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('套餐')
        verbose_name_plural = _('套餐')
        ordering = ['sort_order', 'created_at']

    def __str__(self):
        return self.name


class PlanFeature(models.Model):
    """
    套餐功能表
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='features', verbose_name=_('套餐'))
    feature_code = models.CharField(_('功能代码'), max_length=100)
    feature_name = models.CharField(_('功能名称'), max_length=100)
    description = models.TextField(_('描述'), blank=True)
    value = models.CharField(_('值'), max_length=255, blank=True)
    is_enabled = models.BooleanField(_('是否启用'), default=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('套餐功能')
        verbose_name_plural = _('套餐功能')
        ordering = ['feature_code']
        unique_together = ['plan', 'feature_code']

    def __str__(self):
        return f"{self.plan.name} - {self.feature_name}"


class Tenant(models.Model):
    """
    租户表
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', _('活跃')
        SUSPENDED = 'suspended', _('已暂停')
        CANCELLED = 'cancelled', _('已取消')
        PENDING = 'pending', _('待开通')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('名称'), max_length=100)
    slug = models.SlugField(_('标识'), unique=True, max_length=100)
    domain = models.CharField(_('域名'), max_length=255, blank=True)
    logo = models.ImageField(_('Logo'), upload_to='tenant_logos/', blank=True, null=True)
    description = models.TextField(_('描述'), blank=True)
    status = models.CharField(_('状态'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, related_name='tenants', verbose_name=_('套餐'))
    billing_date = models.DateField(_('账单日期'), null=True, blank=True)
    stripe_customer_id = models.CharField(_('Stripe 客户 ID'), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_tenants', verbose_name=_('创建者'))
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('租户')
        verbose_name_plural = _('租户')
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class TenantSubscription(models.Model):
    """
    租户订阅表
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', _('活跃')
        CANCELLED = 'cancelled', _('已取消')
        PAST_DUE = 'past_due', _('已逾期')
        TRIAL = 'trial', _('试用中')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='subscriptions', verbose_name=_('租户'))
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='subscriptions', verbose_name=_('套餐'))
    status = models.CharField(_('状态'), max_length=20, choices=Status.choices, default=Status.TRIAL)
    start_date = models.DateTimeField(_('开始日期'), default=timezone.now)
    end_date = models.DateTimeField(_('结束日期'), null=True, blank=True)
    auto_renew = models.BooleanField(_('自动续费'), default=True)
    stripe_subscription_id = models.CharField(_('Stripe 订阅 ID'), max_length=255, blank=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('租户订阅')
        verbose_name_plural = _('租户订阅')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tenant.name} - {self.plan.name}"


class TenantConfig(models.Model):
    """
    租户配置表
    """
    class Category(models.TextChoices):
        GENERAL = 'general', _('通用')
        BRANDING = 'branding', _('品牌')
        SECURITY = 'security', _('安全')
        INTEGRATION = 'integration', _('集成')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='configs', verbose_name=_('租户'))
    key = models.CharField(_('配置键'), max_length=100)
    value = models.TextField(_('配置值'))
    category = models.CharField(_('分类'), max_length=50, choices=Category.choices, default=Category.GENERAL)
    description = models.TextField(_('描述'), blank=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('租户配置')
        verbose_name_plural = _('租户配置')
        unique_together = ['tenant', 'key']
        ordering = ['category', 'key']

    def __str__(self):
        return f"{self.tenant.name} - {self.key}"


class Permission(models.Model):
    """
    权限表
    """
    class Module(models.TextChoices):
        TENANT = 'tenant', _('租户')
        USER = 'user', _('用户')
        BILLING = 'billing', _('计费')
        ANALYTICS = 'analytics', _('分析')
        SYSTEM = 'system', _('系统')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('名称'), max_length=100)
    slug = models.SlugField(_('标识'), unique=True, max_length=100)
    description = models.TextField(_('描述'), blank=True)
    module = models.CharField(_('模块'), max_length=50, choices=Module.choices)
    is_active = models.BooleanField(_('是否启用'), default=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('权限')
        verbose_name_plural = _('权限')
        ordering = ['module', 'slug']

    def __str__(self):
        return f"{self.get_module_display()}: {self.name}"


class Role(models.Model):
    """
    角色表
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='roles', null=True, blank=True, verbose_name=_('租户'))
    name = models.CharField(_('名称'), max_length=100)
    slug = models.SlugField(_('标识'), max_length=100)
    description = models.TextField(_('描述'), blank=True)
    is_system = models.BooleanField(_('是否系统角色'), default=False)
    is_active = models.BooleanField(_('是否启用'), default=True)
    permissions = models.ManyToManyField(Permission, related_name='roles', blank=True, verbose_name=_('权限'))
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('角色')
        verbose_name_plural = _('角色')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'slug'], name='unique_role_slug'),
            models.UniqueConstraint(fields=['tenant', 'name'], name='unique_role_name'),
        ]

    def __str__(self):
        return f"{self.tenant.name if self.tenant else 'System'} - {self.name}"


class TenantMember(models.Model):
    """
    租户成员表
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='members', verbose_name=_('租户'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships', verbose_name=_('用户'))
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, related_name='members', verbose_name=_('角色'))
    is_active = models.BooleanField(_('是否启用'), default=True)
    joined_at = models.DateTimeField(_('加入时间'), auto_now_add=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invited_members', verbose_name=_('邀请者'))

    class Meta:
        app_label = 'saas'
        verbose_name = _('租户成员')
        verbose_name_plural = _('租户成员')
        unique_together = ['tenant', 'user']
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name}"


class APILimitRule(models.Model):
    """
    API 限流规则表（路由级精细化控制）

    用于定义特定 API 路由的限流策略，优先级高于套餐和租户级配置。

    示例：
      - 限制 /api/export/ 每 IP 每小时 10 次
      - 限制 /saas/api/tenants/ 每用户每分钟 30 次
    """
    class RuleType(models.TextChoices):
        IP = 'ip', 'IP 限流'
        USER = 'user', '用户限流'
        TENANT = 'tenant', '租户限流'
        ENDPOINT = 'endpoint', '端点限流'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('规则名称'), max_length=100)
    url_pattern = models.CharField(
        _('URL 模式'),
        max_length=500,
        help_text='支持通配符匹配，如 /api/export/* 或正则 ^/saas/api/tenants/'
    )
    throttle_type = models.CharField(
        _('限流类型'),
        max_length=20,
        choices=RuleType.choices,
        default=RuleType.IP,
    )
    rate = models.CharField(
        _('速率限制'),
        max_length=50,
        default='100/h',
        help_text='格式: 次数/周期，如 100/h(每小时100次), 10/m(每分钟10次), 1000/d(每天1000次)'
    )
    is_active = models.BooleanField(_('是否启用'), default=True)
    use_regex = models.BooleanField(
        _('使用正则匹配'),
        default=False,
        help_text='启用后 url_pattern 将作为正则表达式解析',
    )
    priority = models.IntegerField(
        _('优先级'),
        default=0,
        help_text='数值越小优先级越高，用于多规则匹配时选择最优规则',
    )
    description = models.TextField(_('描述'), blank=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('API 限流规则')
        verbose_name_plural = _('API 限流规则')
        ordering = ['priority', '-created_at']

    def __str__(self):
        return f"{self.name} [{self.get_throttle_type_display()}] → {self.rate}"

    def matches(self, path: str) -> bool:
        """
        检查请求路径是否匹配此规则。

        Args:
            path: 请求路径，如 /saas/api/tenants/

        Returns:
            True 如果路径匹配
        """
        if self.use_regex:
            try:
                return bool(re.match(self.url_pattern, path))
            except re.error:
                return False

        # 通配符匹配：将 * 转换为匹配任意字符（不含 /）
        pattern = self.url_pattern
        if '*' in pattern:
            # 转义正则特殊字符，再替换 * 为 .*
            escaped = re.escape(pattern).replace(r'\*', '.*')
            try:
                return bool(re.match(f"^{escaped}$", path))
            except re.error:
                return False

        # 精确前缀匹配
        return path.startswith(pattern)


class Order(models.Model):
    """
    订单表
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('待支付')
        PAID = 'paid', _('已支付')
        CANCELLED = 'cancelled', _('已取消')
        REFUNDED = 'refunded', _('已退款')

    class PaymentMethod(models.TextChoices):
        STRIPE = 'stripe', _('Stripe')
        ALIPAY = 'alipay', _('支付宝')
        WECHAT = 'wechat', _('微信支付')
        BANK_TRANSFER = 'bank_transfer', _('银行转账')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(_('订单号'), unique=True, max_length=100)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='orders', verbose_name=_('租户'))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='orders', verbose_name=_('用户'))
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='orders', verbose_name=_('套餐'))
    amount = models.DecimalField(_('金额'), max_digits=10, decimal_places=2)
    currency = models.CharField(_('货币'), max_length=10, default='CNY')
    status = models.CharField(_('状态'), max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField(_('支付方式'), max_length=50, choices=PaymentMethod.choices, blank=True)
    payment_date = models.DateTimeField(_('支付日期'), null=True, blank=True)
    stripe_payment_id = models.CharField(_('Stripe 支付 ID'), max_length=255, blank=True)
    notes = models.TextField(_('备注'), blank=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('订单')
        verbose_name_plural = _('订单')
        ordering = ['-created_at']

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)


class Invoice(models.Model):
    """
    发票表
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('待支付')
        PAID = 'paid', _('已支付')
        OVERDUE = 'overdue', _('已逾期')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_number = models.CharField(_('发票号'), unique=True, max_length=100)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice', verbose_name=_('订单'))
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='invoices', verbose_name=_('租户'))
    amount = models.DecimalField(_('金额'), max_digits=10, decimal_places=2)
    currency = models.CharField(_('货币'), max_length=10, default='CNY')
    status = models.CharField(_('状态'), max_length=20, choices=Status.choices, default=Status.PENDING)
    due_date = models.DateField(_('到期日'))
    paid_date = models.DateField(_('支付日期'), null=True, blank=True)
    pdf_file = models.FileField(_('PDF 文件'), upload_to='invoices/', blank=True, null=True)
    sent_at = models.DateTimeField(_('发送时间'), null=True, blank=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('发票')
        verbose_name_plural = _('发票')
        ordering = ['-created_at']

    def __str__(self):
        return self.invoice_number

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = f"INV-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
