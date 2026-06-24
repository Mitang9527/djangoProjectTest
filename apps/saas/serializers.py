"""
SaaS 后台管理系统 - API 序列化器
"""
from rest_framework import serializers
from .models import (
    Plan,
    PlanFeature,
    Tenant,
    TenantSubscription,
    TenantConfig,
    Permission,
    Role,
    TenantMember,
    Order,
    Invoice
)


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {'slug': {'validators': []}}  # 移除自动 UniqueValidator，由 validate_slug 接管

    def validate_slug(self, value):
        qs = Plan.objects.filter(slug=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'标识：{value}当前已存在')
        return value

    def validate_name(self, value):
        qs = Plan.objects.filter(name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'名称：{value}当前已存在')
        return value


class PlanFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanFeature
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def validate(self, attrs):
        plan = attrs.get('plan', self.instance.plan if self.instance else None)
        code = attrs.get('feature_code', self.instance.feature_code if self.instance else '')
        if plan and code:
            qs = PlanFeature.objects.filter(plan=plan, feature_code=code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(f'功能代码：{code}当前已存在')
        return attrs


class TenantSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True, default='---', allow_null=True)
    plan_slug = serializers.CharField(source='plan.slug', read_only=True, default='', allow_null=True)
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Tenant
        fields = '__all__'
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
        extra_kwargs = {'slug': {'validators': []}}  # 移除自动 UniqueValidator，由 validate_slug 接管

    def validate_slug(self, value):
        qs = Tenant.objects.filter(slug=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'标识：{value}当前已存在')
        return value

    def validate_name(self, value):
        qs = Tenant.objects.filter(name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'名称：{value}当前已存在')
        return value


class TenantSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSubscription
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class TenantConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantConfig
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def validate(self, attrs):
        tenant = attrs.get('tenant', self.instance.tenant if self.instance else None)
        key = attrs.get('key', self.instance.key if self.instance else '')
        if tenant and key:
            qs = TenantConfig.objects.filter(tenant=tenant, key=key)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(f'配置键：{key}当前已存在')
        return attrs


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'slug': {'validators': []}}  # 移除自动 UniqueValidator，由 validate_slug 接管

    def validate_slug(self, value):
        qs = Permission.objects.filter(slug=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'标识：{value}当前已存在')
        return value

    def validate_name(self, value):
        qs = Permission.objects.filter(name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'名称：{value}当前已存在')
        return value


class RoleSerializer(serializers.ModelSerializer):
    permission_count = serializers.IntegerField(source='permissions.count', read_only=True)

    class Meta:
        model = Role
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def validate(self, attrs):
        tenant = attrs.get('tenant', self.instance.tenant if self.instance else None)
        slug = attrs.get('slug', self.instance.slug if self.instance else '')
        name = attrs.get('name', self.instance.name if self.instance else '')

        # 标识唯一性
        if tenant is not None and slug:
            qs = Role.objects.filter(slug=slug, tenant=tenant)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'slug': f'标识：{slug}当前已存在'})

        # 名称唯一性（同一租户下）
        if tenant is not None and name:
            qs = Role.objects.filter(name=name, tenant=tenant)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'name': f'名称：{name}当前已存在'})

        return attrs


class TenantMemberSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True, default='', allow_null=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True, default='---', allow_null=True)
    role_slug = serializers.CharField(source='role.slug', read_only=True, default='', allow_null=True)

    class Meta:
        model = TenantMember
        fields = '__all__'
        read_only_fields = ['id', 'joined_at']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def validate(self, attrs):
        tenant = attrs.get('tenant', self.instance.tenant if self.instance else None)
        user = attrs.get('user', self.instance.user if self.instance else None)
        if tenant and user:
            qs = TenantMember.objects.filter(tenant=tenant, user=user)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError('该用户已是此租户的成员')
        return attrs


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['id', 'order_number', 'created_at', 'updated_at']


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = ['id', 'invoice_number', 'created_at', 'updated_at']
