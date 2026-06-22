"""
SaaS 后台管理系统 - 数据库模型
"""
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
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('Name'), max_length=100)
    slug = models.SlugField(_('Slug'), unique=True, max_length=100)
    description = models.TextField(_('Description'), blank=True)
    price = models.DecimalField(_('Monthly Price'), max_digits=10, decimal_places=2)
    price_yearly = models.DecimalField(_('Yearly Price'), max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(_('Currency'), max_length=10, default='CNY')
    max_users = models.IntegerField(_('Max Users'), default=10)
    max_storage_mb = models.IntegerField(_('Max Storage (MB)'), default=1024)
    is_active = models.BooleanField(_('Is Active'), default=True)
    is_featured = models.BooleanField(_('Is Featured'), default=False)
    sort_order = models.IntegerField(_('Sort Order'), default=0)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Plan')
        verbose_name_plural = _('Plans')
        ordering = ['sort_order', 'created_at']

    def __str__(self):
        return self.name


class PlanFeature(models.Model):
    """
    套餐功能表
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='features')
    feature_code = models.CharField(_('Feature Code'), max_length=100)
    feature_name = models.CharField(_('Feature Name'), max_length=100)
    description = models.TextField(_('Description'), blank=True)
    value = models.CharField(_('Value'), max_length=255, blank=True)
    is_enabled = models.BooleanField(_('Is Enabled'), default=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('Plan Feature')
        verbose_name_plural = _('Plan Features')
        ordering = ['feature_code']
        unique_together = ['plan', 'feature_code']

    def __str__(self):
        return f"{self.plan.name} - {self.feature_name}"


class Tenant(models.Model):
    """
    租户表
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        SUSPENDED = 'suspended', _('Suspended')
        CANCELLED = 'cancelled', _('Cancelled')
        PENDING = 'pending', _('Pending')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('Tenant Name'), max_length=100)
    slug = models.SlugField(_('Slug'), unique=True, max_length=100)
    domain = models.CharField(_('Domain'), max_length=255, blank=True)
    logo = models.ImageField(_('Logo'), upload_to='tenant_logos/', blank=True, null=True)
    description = models.TextField(_('Description'), blank=True)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, related_name='tenants')
    billing_date = models.DateField(_('Billing Date'), null=True, blank=True)
    stripe_customer_id = models.CharField(_('Stripe Customer ID'), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_tenants')
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Tenant')
        verbose_name_plural = _('Tenants')
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class TenantSubscription(models.Model):
    """
    租户订阅表
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        CANCELLED = 'cancelled', _('Cancelled')
        PAST_DUE = 'past_due', _('Past Due')
        TRIAL = 'trial', _('Trial')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='subscriptions')
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.TRIAL)
    start_date = models.DateTimeField(_('Start Date'), default=timezone.now)
    end_date = models.DateTimeField(_('End Date'), null=True, blank=True)
    auto_renew = models.BooleanField(_('Auto Renew'), default=True)
    stripe_subscription_id = models.CharField(_('Stripe Subscription ID'), max_length=255, blank=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Tenant Subscription')
        verbose_name_plural = _('Tenant Subscriptions')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tenant.name} - {self.plan.name}"


class TenantConfig(models.Model):
    """
    租户配置表
    """
    class Category(models.TextChoices):
        GENERAL = 'general', _('General')
        BRANDING = 'branding', _('Branding')
        SECURITY = 'security', _('Security')
        INTEGRATION = 'integration', _('Integration')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='configs')
    key = models.CharField(_('Config Key'), max_length=100)
    value = models.TextField(_('Config Value'))
    category = models.CharField(_('Category'), max_length=50, choices=Category.choices, default=Category.GENERAL)
    description = models.TextField(_('Description'), blank=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Tenant Config')
        verbose_name_plural = _('Tenant Configs')
        unique_together = ['tenant', 'key']
        ordering = ['category', 'key']

    def __str__(self):
        return f"{self.tenant.name} - {self.key}"


class Permission(models.Model):
    """
    权限表
    """
    class Module(models.TextChoices):
        TENANT = 'tenant', _('Tenant')
        USER = 'user', _('User')
        BILLING = 'billing', _('Billing')
        ANALYTICS = 'analytics', _('Analytics')
        SYSTEM = 'system', _('System')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_('Permission Name'), max_length=100)
    slug = models.SlugField(_('Slug'), unique=True, max_length=100)
    description = models.TextField(_('Description'), blank=True)
    module = models.CharField(_('Module'), max_length=50, choices=Module.choices)
    is_active = models.BooleanField(_('Is Active'), default=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)

    class Meta:
        verbose_name = _('Permission')
        verbose_name_plural = _('Permissions')
        ordering = ['module', 'slug']

    def __str__(self):
        return f"{self.get_module_display()}: {self.name}"


class Role(models.Model):
    """
    角色表
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='roles', null=True, blank=True)
    name = models.CharField(_('Role Name'), max_length=100)
    slug = models.SlugField(_('Slug'), max_length=100)
    description = models.TextField(_('Description'), blank=True)
    is_system = models.BooleanField(_('Is System Role'), default=False)
    is_active = models.BooleanField(_('Is Active'), default=True)
    permissions = models.ManyToManyField(Permission, related_name='roles', blank=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Role')
        verbose_name_plural = _('Roles')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'slug'], name='unique_role_slug'),
        ]

    def __str__(self):
        return f"{self.tenant.name if self.tenant else 'System'} - {self.name}"


class TenantMember(models.Model):
    """
    租户成员表
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships')
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, related_name='members')
    is_active = models.BooleanField(_('Is Active'), default=True)
    joined_at = models.DateTimeField(_('Joined At'), auto_now_add=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invited_members')

    class Meta:
        verbose_name = _('Tenant Member')
        verbose_name_plural = _('Tenant Members')
        unique_together = ['tenant', 'user']
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name}"


class Order(models.Model):
    """
    订单表
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PAID = 'paid', _('Paid')
        CANCELLED = 'cancelled', _('Cancelled')
        REFUNDED = 'refunded', _('Refunded')

    class PaymentMethod(models.TextChoices):
        STRIPE = 'stripe', _('Stripe')
        ALIPAY = 'alipay', _('Alipay')
        WECHAT = 'wechat', _('WeChat')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(_('Order Number'), unique=True, max_length=100)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='orders')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='orders')
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='orders')
    amount = models.DecimalField(_('Amount'), max_digits=10, decimal_places=2)
    currency = models.CharField(_('Currency'), max_length=10, default='CNY')
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField(_('Payment Method'), max_length=50, choices=PaymentMethod.choices, blank=True)
    payment_date = models.DateTimeField(_('Payment Date'), null=True, blank=True)
    stripe_payment_id = models.CharField(_('Stripe Payment ID'), max_length=255, blank=True)
    notes = models.TextField(_('Notes'), blank=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Order')
        verbose_name_plural = _('Orders')
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
        PENDING = 'pending', _('Pending')
        PAID = 'paid', _('Paid')
        OVERDUE = 'overdue', _('Overdue')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_number = models.CharField(_('Invoice Number'), unique=True, max_length=100)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='invoice')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='invoices')
    amount = models.DecimalField(_('Amount'), max_digits=10, decimal_places=2)
    currency = models.CharField(_('Currency'), max_length=10, default='CNY')
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.PENDING)
    due_date = models.DateField(_('Due Date'))
    paid_date = models.DateField(_('Paid Date'), null=True, blank=True)
    pdf_file = models.FileField(_('PDF File'), upload_to='invoices/', blank=True, null=True)
    sent_at = models.DateTimeField(_('Sent At'), null=True, blank=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        verbose_name = _('Invoice')
        verbose_name_plural = _('Invoices')
        ordering = ['-created_at']

    def __str__(self):
        return self.invoice_number

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = f"INV-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
