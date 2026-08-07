"""
SaaS 后台管理系统 - 数据库模型
"""
import re
import uuid
from framework.random_utils.random_utils import gen_order_no
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
            self.order_number = gen_order_no("ORD")
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
            self.invoice_number = gen_order_no("INV")
        super().save(*args, **kwargs)


class GlobalConfig(models.Model):
    """
    全局配置表 - 配置中心核心模型
    支持动态配置存储，分类管理，版本历史
    """
    class ConfigType(models.TextChoices):
        STRING = 'string', _('字符串')
        INTEGER = 'integer', _('整数')
        BOOLEAN = 'boolean', _('布尔值')
        FLOAT = 'float', _('浮点数')
        JSON = 'json', _('JSON对象')

    class Category(models.TextChoices):
        SYSTEM = 'system', _('系统配置')
        FEATURE = 'feature', _('功能配置')
        BUSINESS = 'business', _('业务配置')
        SECURITY = 'security', _('安全配置')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(_('配置键'), max_length=100, unique=True, db_index=True,
                           help_text='唯一配置标识，推荐使用点号分隔，如 system.timeout')
    name = models.CharField(_('配置名称'), max_length=200)
    description = models.TextField(_('描述'), blank=True)
    value = models.TextField(_('配置值'), help_text='存储配置的原始值')
    config_type = models.CharField(_('类型'), max_length=20, choices=ConfigType.choices, default=ConfigType.STRING)
    category = models.CharField(_('分类'), max_length=50, choices=Category.choices, default=Category.SYSTEM)
    default_value = models.TextField(_('默认值'), blank=True, help_text='默认配置值')
    is_active = models.BooleanField(_('是否启用'), default=True, db_index=True)
    is_public = models.BooleanField(_('是否公开'), default=False, help_text='公开配置可被前端直接读取')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='created_global_configs', verbose_name=_('创建者'))
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='updated_global_configs', verbose_name=_('更新者'))
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('全局配置')
        verbose_name_plural = _('全局配置')
        ordering = ['category', 'key']

    def __str__(self):
        return f"{self.key}: {self.value}"

    @property
    def parsed_value(self):
        """根据类型解析配置值"""
        if self.value is None or self.value == '':
            return self.parse_value(self.default_value) if self.default_value else None
        return self.parse_value(self.value)

    @staticmethod
    def parse_value(value_str, config_type=ConfigType.STRING):
        """解析配置值为对应类型"""
        if value_str is None or value_str == '':
            return None
        try:
            if config_type == GlobalConfig.ConfigType.INTEGER:
                return int(value_str)
            elif config_type == GlobalConfig.ConfigType.BOOLEAN:
                return value_str.lower() in ('true', '1', 'yes', 'on')
            elif config_type == GlobalConfig.ConfigType.FLOAT:
                return float(value_str)
            elif config_type == GlobalConfig.ConfigType.JSON:
                import json
                return json.loads(value_str)
            return value_str
        except (ValueError, json.JSONDecodeError):
            return value_str


class FeatureFlag(models.Model):
    """
    特性开关/灰度发布模型
    支持按用户、租户、比例灰度发布
    """
    class Status(models.TextChoices):
        DRAFT = 'draft', _('草稿')
        ACTIVE = 'active', _('启用')
        PAUSED = 'paused', _('暂停')
        ARCHIVED = 'archived', _('已归档')

    class RolloutStrategy(models.TextChoices):
        ALL = 'all', _('全部用户')
        INTERNAL = 'internal', _('仅内部用户')
        PERCENTAGE = 'percentage', _('按比例')
        USERS = 'users', _('指定用户')
        TENANTS = 'tenants', _('指定租户')
        USER_GROUPS = 'user_groups', _('指定用户组')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(_('特性键'), max_length=100, unique=True, db_index=True,
                           help_text='唯一特性标识，如 feature.new_ui')
    name = models.CharField(_('特性名称'), max_length=200)
    description = models.TextField(_('描述'), blank=True)
    status = models.CharField(_('状态'), max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    rollout_strategy = models.CharField(_('发布策略'), max_length=20, choices=RolloutStrategy.choices,
                                        default=RolloutStrategy.ALL)
    rollout_percentage = models.PositiveIntegerField(_('发布比例'), default=100,
                                                     validators=[MinValueValidator(0), MaxValueValidator(100)],
                                                     help_text='0-100，仅在 percentage 策略下生效')
    target_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True,
                                          related_name='feature_flags', verbose_name=_('目标用户'))
    target_tenants = models.ManyToManyField(Tenant, blank=True,
                                            related_name='feature_flags', verbose_name=_('目标租户'))
    starts_at = models.DateTimeField(_('开始时间'), null=True, blank=True, db_index=True,
                                     help_text='特性开始生效时间')
    ends_at = models.DateTimeField(_('结束时间'), null=True, blank=True, db_index=True,
                                   help_text='特性结束生效时间')
    metadata = models.JSONField(_('元数据'), default=dict, blank=True, help_text='额外的配置信息')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='created_feature_flags', verbose_name=_('创建者'))
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='updated_feature_flags', verbose_name=_('更新者'))
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('特性开关')
        verbose_name_plural = _('特性开关')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.key} ({self.get_status_display()})"

    def is_enabled_for_user(self, user, tenant=None):
        """
        判断特性是否对指定用户启用
        """
        # 检查基本状态
        if self.status != self.Status.ACTIVE:
            return False

        # 检查时间范围
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False

        # 根据策略判断
        if self.rollout_strategy == self.RolloutStrategy.ALL:
            return True

        if self.rollout_strategy == self.RolloutStrategy.INTERNAL:
            return user.is_staff or user.is_superuser

        if self.rollout_strategy == self.RolloutStrategy.USERS:
            return self.target_users.filter(id=user.id).exists()

        if self.rollout_strategy == self.RolloutStrategy.TENANTS:
            if tenant:
                return self.target_tenants.filter(id=tenant.id).exists()
            return False

        if self.rollout_strategy == self.RolloutStrategy.PERCENTAGE:
            # 使用用户ID哈希确定是否在比例内，确保同一用户结果稳定
            import hashlib
            user_hash = int(hashlib.md5(str(user.id).encode()).hexdigest(), 16) % 100
            return user_hash < self.rollout_percentage

        if self.rollout_strategy == self.RolloutStrategy.USER_GROUPS:
            # 用户组逻辑可以在这里扩展
            return False

        return False


class ConfigHistory(models.Model):
    """
    配置变更历史记录
    用于追踪配置变更，支持回滚
    """
    class OperationType(models.TextChoices):
        CREATE = 'create', _('创建')
        UPDATE = 'update', _('更新')
        DELETE = 'delete', _('删除')
        ROLLBACK = 'rollback', _('回滚')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config_key = models.CharField(_('配置键'), max_length=100, db_index=True)
    config_type = models.CharField(_('配置类型'), max_length=50)  # 'global_config' 或 'feature_flag'
    operation = models.CharField(_('操作类型'), max_length=20, choices=OperationType.choices)
    old_value = models.TextField(_('旧值'), blank=True, null=True)
    new_value = models.TextField(_('新值'), blank=True, null=True)
    diff = models.JSONField(_('差异详情'), default=dict, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 related_name='config_histories', verbose_name=_('操作者'))
    created_at = models.DateTimeField(_('操作时间'), auto_now_add=True, db_index=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('配置历史')
        verbose_name_plural = _('配置历史')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.config_key} - {self.get_operation_display()} at {self.created_at}"


class ThrottleLog(models.Model):
    """
    限流命中日志 - 记录所有被限流的请求
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    throttle_type = models.CharField(
        _('限流类型'),
        max_length=20,
        choices=APILimitRule.RuleType.choices,
        default='ip',
    )
    identifier = models.CharField(_('限流标识'), max_length=255, help_text='IP地址/用户ID/租户ID等')
    path = models.CharField(_('请求路径'), max_length=500)
    method = models.CharField(_('请求方法'), max_length=10)
    rule = models.ForeignKey(
        APILimitRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='throttle_logs',
        verbose_name=_('触发的规则'),
    )
    limit = models.IntegerField(_('限制次数'), null=True, blank=True)
    window_seconds = models.IntegerField(_('窗口秒数'), null=True, blank=True)
    user_agent = models.TextField(_('User-Agent'), blank=True)
    remote_addr = models.GenericIPAddressField(_('客户端IP'), null=True, blank=True)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='throttle_logs',
        verbose_name=_('租户'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='throttle_logs',
        verbose_name=_('用户'),
    )
    created_at = models.DateTimeField(_('触发时间'), auto_now_add=True, db_index=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('限流日志')
        verbose_name_plural = _('限流日志')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['throttle_type', '-created_at']),
            models.Index(fields=['identifier', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.get_throttle_type_display()} - {self.identifier} - {self.path}"


class ThrottleStats(models.Model):
    """
    限流统计 - 按时间维度聚合的限流统计数据
    """
    class Period(models.TextChoices):
        MINUTE = 'minute', _('分钟')
        HOUR = 'hour', _('小时')
        DAY = 'day', _('天')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.CharField(_('统计周期'), max_length=10, choices=Period.choices, default=Period.HOUR)
    period_start = models.DateTimeField(_('周期开始时间'), db_index=True)
    throttle_type = models.CharField(
        _('限流类型'),
        max_length=20,
        choices=APILimitRule.RuleType.choices,
        default='ip',
    )
    identifier = models.CharField(_('限流标识'), max_length=255, blank=True)
    path = models.CharField(_('请求路径'), max_length=500, blank=True)
    rule = models.ForeignKey(
        APILimitRule,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='stats',
        verbose_name=_('限流规则'),
    )
    request_count = models.IntegerField(_('总请求数'), default=0)
    throttle_count = models.IntegerField(_('被限流次数'), default=0)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='throttle_stats',
        verbose_name=_('租户'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('限流统计')
        verbose_name_plural = _('限流统计')
        unique_together = ['period', 'period_start', 'throttle_type', 'identifier', 'path', 'tenant']
        ordering = ['-period_start']
        indexes = [
            models.Index(fields=['period', 'period_start']),
            models.Index(fields=['throttle_type', '-period_start']),
        ]

    def __str__(self):
        return f"{self.get_period_display()} - {self.get_throttle_type_display()} - {self.throttle_count}/{self.request_count}"


class ThrottleAlert(models.Model):
    """
    限流告警 - 当限流达到阈值时触发告警
    """
    class AlertType(models.TextChoices):
        RATE_EXCEEDED = 'rate_exceeded', _('频率超限')
        THRESHOLD_REACHED = 'threshold_reached', _('阈值告警')
        ANOMALY_DETECTED = 'anomaly_detected', _('异常检测')

    class AlertLevel(models.TextChoices):
        INFO = 'info', _('信息')
        WARNING = 'warning', _('警告')
        ERROR = 'error', _('错误')
        CRITICAL = 'critical', _('严重')

    class AlertStatus(models.TextChoices):
        PENDING = 'pending', _('待处理')
        SENT = 'sent', _('已发送')
        ACKNOWLEDGED = 'acknowledged', _('已确认')
        RESOLVED = 'resolved', _('已解决')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert_type = models.CharField(_('告警类型'), max_length=30, choices=AlertType.choices)
    alert_level = models.CharField(_('告警级别'), max_length=20, choices=AlertLevel.choices, default=AlertLevel.WARNING)
    status = models.CharField(_('状态'), max_length=20, choices=AlertStatus.choices, default=AlertStatus.PENDING)
    title = models.CharField(_('告警标题'), max_length=200)
    message = models.TextField(_('告警内容'))
    throttle_type = models.CharField(
        _('限流类型'),
        max_length=20,
        choices=APILimitRule.RuleType.choices,
        blank=True,
    )
    identifier = models.CharField(_('限流标识'), max_length=255, blank=True)
    path = models.CharField(_('请求路径'), max_length=500, blank=True)
    rule = models.ForeignKey(
        APILimitRule,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alerts',
        verbose_name=_('关联规则'),
    )
    throttle_count = models.IntegerField(_('限流次数'), default=0)
    threshold = models.IntegerField(_('告警阈值'), null=True, blank=True)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='throttle_alerts',
        verbose_name=_('租户'),
    )
    sent_at = models.DateTimeField(_('发送时间'), null=True, blank=True)
    acknowledged_at = models.DateTimeField(_('确认时间'), null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_throttle_alerts',
        verbose_name=_('确认人'),
    )
    resolved_at = models.DateTimeField(_('解决时间'), null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_throttle_alerts',
        verbose_name=_('解决人'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('限流告警')
        verbose_name_plural = _('限流告警')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['alert_level', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.get_alert_level_display()}] {self.title}"


class ThrottleAlertRule(models.Model):
    """
    告警规则配置 - 配置何时触发告警
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('规则名称'), max_length=100)
    description = models.TextField(_('描述'), blank=True)
    throttle_type = models.CharField(
        _('限流类型'),
        max_length=20,
        choices=APILimitRule.RuleType.choices,
        blank=True,
        help_text=_('留空表示所有类型'),
    )
    throttle_rule = models.ForeignKey(
        APILimitRule,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alert_rules',
        verbose_name=_('关联限流规则'),
    )
    threshold_count = models.IntegerField(_('阈值次数'), default=10, help_text=_('达到此次数触发告警'))
    time_window = models.IntegerField(_('时间窗口(秒)'), default=3600, help_text=_('在多少秒内达到阈值'))
    alert_level = models.CharField(_('告警级别'), max_length=20, choices=ThrottleAlert.AlertLevel.choices, default=ThrottleAlert.AlertLevel.WARNING)
    is_active = models.BooleanField(_('是否启用'), default=True)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='throttle_alert_rules',
        verbose_name=_('租户'),
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        app_label = 'saas'
        verbose_name = _('告警规则配置')
        verbose_name_plural = _('告警规则配置')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.threshold_count}/{self.time_window}s"
