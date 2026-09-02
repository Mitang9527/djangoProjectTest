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
    Department,
    Post,
    UserPost,
    TenantMember,
    Order,
    Invoice,
    GlobalConfig,
    FeatureFlag,
    ConfigHistory,
    TenantInitializationTemplate,
)
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            'id', 'name', 'slug', 'description', 'price', 'price_yearly',
            'currency', 'max_users', 'max_storage_mb', 'is_active',
            'is_featured', 'sort_order', 'created_at', 'updated_at',
        )
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
        fields = (
            'id', 'plan', 'feature_code', 'feature_name', 'description',
            'value', 'is_enabled', 'created_at',
        )
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
    initialization_template = serializers.PrimaryKeyRelatedField(
        queryset=TenantInitializationTemplate.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model = Tenant
        fields = (
            'id', 'name', 'slug', 'domain', 'logo', 'description', 'status',
            'plan', 'plan_name', 'plan_slug', 'initialization_template',
            'billing_date', 'stripe_customer_id',
            'created_by', 'created_at', 'updated_at',
        )
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
        fields = (
            'id', 'tenant', 'plan', 'status', 'start_date', 'end_date',
            'auto_renew', 'stripe_subscription_id', 'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'created_at', 'updated_at']


class TenantConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantConfig
        fields = (
            'id', 'tenant', 'key', 'value', 'category', 'description',
            'created_at', 'updated_at',
        )
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
        fields = (
            'id', 'name', 'slug', 'description', 'module', 'is_active', 'created_at',
        )
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


class PermissionBriefSerializer(serializers.ModelSerializer):
    """权限摘要序列化器（嵌套在 Role 中返回，含名称/标识/模块）"""
    class Meta:
        model = Permission
        fields = ('id', 'name', 'slug', 'module')


class RoleSerializer(serializers.ModelSerializer):
    permission_count = serializers.IntegerField(source='permissions.count', read_only=True)
    # 自定义数据权限部门（仅 data_scope='custom' 时有效；读写，UUID 列表）
    custom_department_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True,
    )

    class Meta:
        model = Role
        fields = (
            'id', 'tenant', 'name', 'slug', 'description', 'is_system',
            'is_active', 'data_scope', 'permissions', 'permission_count',
            'custom_department_ids', 'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'created_at', 'updated_at']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def to_representation(self, instance):
        """输出时将 permissions 从 UUID 列表替换为嵌套权限对象，
        custom_department_ids 从关联表查询填充。"""
        data = super().to_representation(instance)
        data['permissions'] = PermissionBriefSerializer(
            instance.permissions.all(), many=True
        ).data
        data['custom_department_ids'] = [
            str(did)
            for did in instance.data_scope_departments.values_list('department_id', flat=True)
        ]
        return data

    def create(self, validated_data):
        """pop 非模型字段后落库，并同步自定义数据权限部门（对齐参考 create_role）。"""
        custom_department_ids = validated_data.pop('custom_department_ids', [])
        role = super().create(validated_data)
        self._sync_custom_departments(role, custom_department_ids)
        return role

    def update(self, instance, validated_data):
        """更新角色：仅在客户端显式提供 custom_department_ids 时全量替换，
        未提供则保持既有部门关联（避免 PATCH 其它字段误清数据权限）。"""
        custom_department_ids = validated_data.pop('custom_department_ids', None)
        role = super().update(instance, validated_data)
        if custom_department_ids is not None:
            self._sync_custom_departments(role, custom_department_ids)
        return role

    def _sync_custom_departments(self, role, department_ids):
        from .services import TenantOrgService

        try:
            TenantOrgService.sync_role_custom_departments(role, department_ids or [])
        except ValueError as e:
            raise serializers.ValidationError({'custom_department_ids': str(e)})

    def validate(self, attrs):
        tenant = attrs.get('tenant', self.instance.tenant if self.instance else None)
        slug = attrs.get('slug', self.instance.slug if self.instance else '')
        name = attrs.get('name', self.instance.name if self.instance else '')
        data_scope = attrs.get('data_scope', self.instance.data_scope if self.instance else '')
        custom_department_ids = attrs.get(
            'custom_department_ids',
            getattr(self.instance, 'custom_department_ids', []) if self.instance else [],
        )

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

        # 自定义数据权限必须提供且部门存在（非 custom 时忽略并清空）
        if data_scope == Role.DataScope.CUSTOM:
            if not custom_department_ids:
                raise serializers.ValidationError(
                    {'custom_department_ids': '数据权限为自定义时必须指定部门'}
                )
            if tenant is not None:
                from .models import Department
                ids = {str(did) for did in custom_department_ids}
                existing = {
                    str(did) for did in Department.objects.filter(
                        tenant=tenant, id__in=ids,
                    ).values_list('id', flat=True)
                }
                if existing != ids:
                    raise serializers.ValidationError(
                        {'custom_department_ids': '部分部门不存在或不属于当前租户'}
                    )
        else:
            # 非 custom：忽略客户端传入的 custom_department_ids，置空
            attrs['custom_department_ids'] = []

        return attrs


class DepartmentSerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source='parent.name', read_only=True, default='', allow_null=True)
    leader_username = serializers.CharField(source='leader_user.username', read_only=True, default='', allow_null=True)

    class Meta:
        model = Department
        fields = (
            'id', 'tenant', 'name', 'code', 'parent', 'parent_name',
            'leader_user', 'leader_username', 'sort', 'is_active', 'remark',
            'archived_at', 'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'created_at', 'updated_at', 'archived_at', 'tenant']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def _resolve_tenant(self, attrs):
        """租户来源：请求上下文注入（perform_create 传 tenant，或 request.tenant）"""
        request = self.context.get('request')
        ctx_tenant = getattr(request, 'tenant', None) if request else None
        return (
            attrs.get('tenant')
            or (self.instance.tenant if self.instance else None)
            or ctx_tenant
        )

    def validate(self, attrs):
        from .services import TenantOrgService

        tenant = self._resolve_tenant(attrs)
        code = attrs.get('code', self.instance.code if self.instance else '')
        parent = attrs.get('parent', self.instance.parent if self.instance else None)
        leader_user = attrs.get('leader_user', self.instance.leader_user if self.instance else None)

        # 编码唯一性（租户内）
        if tenant is not None and code:
            qs = Department.objects.filter(tenant=tenant, code=code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'code': f'编码：{code}当前已存在'})

        # 树校验：父不能是自己 / 自己的子孙（对齐参考 is_descendant_department）
        if self.instance and parent is not None:
            if parent.pk == self.instance.pk:
                raise serializers.ValidationError({'parent': '上级部门不能是自己'})
            if TenantOrgService.is_descendant_department(
                tenant, self.instance.pk, parent.pk,
            ):
                raise serializers.ValidationError({'parent': '上级部门不能是自己的子部门'})

        # 上级部门不能是已归档节点
        if parent is not None and getattr(parent, 'archived_at', None):
            raise serializers.ValidationError({'parent': '上级部门已归档，不能作为上级'})

        # 负责人必须是租户成员
        if leader_user is not None:
            if not TenantMember.objects.filter(
                tenant=tenant, user=leader_user, is_active=True,
            ).exists():
                raise serializers.ValidationError(
                    {'leader_user': '负责人必须是当前租户的活跃成员'}
                )

        return attrs


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = (
            'id', 'tenant', 'name', 'code', 'sort', 'is_active', 'remark',
            'archived_at', 'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'created_at', 'updated_at', 'archived_at', 'tenant']
        validators = []  # 移除自动 UniqueTogetherValidator，由 validate() 统一处理

    def validate(self, attrs):
        # 租户来源：请求上下文注入（同 DepartmentSerializer）
        request = self.context.get('request')
        ctx_tenant = getattr(request, 'tenant', None) if request else None
        tenant = (
            attrs.get('tenant')
            or (self.instance.tenant if self.instance else None)
            or ctx_tenant
        )
        code = attrs.get('code', self.instance.code if self.instance else '')
        if tenant is not None and code:
            qs = Post.objects.filter(tenant=tenant, code=code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'code': f'编码：{code}当前已存在'})
        return attrs


class UserPostSerializer(serializers.ModelSerializer):
    post_name = serializers.CharField(source='post.name', read_only=True)
    post_code = serializers.CharField(source='post.code', read_only=True)

    class Meta:
        model = UserPost
        fields = ('id', 'tenant', 'user', 'post', 'post_name', 'post_code', 'created_at')
        read_only_fields = ['id', 'created_at']


class TenantMemberSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True, default='', allow_null=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True, default='---', allow_null=True)
    role_slug = serializers.CharField(source='role.slug', read_only=True, default='', allow_null=True)
    department_name = serializers.CharField(source='department.name', read_only=True, default='', allow_null=True)

    class Meta:
        model = TenantMember
        fields = (
            'id', 'tenant', 'tenant_name', 'user', 'username', 'user_email',
            'role', 'role_name', 'role_slug', 'department', 'department_name',
            'is_active', 'joined_at', 'invited_by',
        )
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
        fields = (
            'id', 'order_number', 'tenant', 'user', 'plan', 'amount', 'currency',
            'status', 'payment_method', 'payment_date', 'stripe_payment_id',
            'notes', 'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'order_number', 'created_at', 'updated_at']


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = (
            'id', 'invoice_number', 'order', 'tenant', 'amount', 'currency',
            'status', 'due_date', 'paid_date', 'pdf_file', 'sent_at',
            'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'invoice_number', 'created_at', 'updated_at']


class GlobalConfigSerializer(serializers.ModelSerializer):
    parsed_value = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, default='')
    updated_by_name = serializers.CharField(source='updated_by.username', read_only=True, default='')

    class Meta:
        model = GlobalConfig
        fields = (
            'id', 'key', 'name', 'description', 'value', 'parsed_value',
            'config_type', 'category', 'default_value', 'is_active', 'is_public',
            'created_by', 'created_by_name', 'updated_by', 'updated_by_name',
            'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'updated_by']
        extra_kwargs = {'key': {'validators': []}}

    @extend_schema_field(OpenApiTypes.ANY)
    def get_parsed_value(self, obj):
        return obj.parsed_value

    def validate_key(self, value):
        qs = GlobalConfig.objects.filter(key=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'配置键：{value}当前已存在')
        return value


class FeatureFlagSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, default='')
    updated_by_name = serializers.CharField(source='updated_by.username', read_only=True, default='')
    target_user_count = serializers.IntegerField(source='target_users.count', read_only=True)
    target_tenant_count = serializers.IntegerField(source='target_tenants.count', read_only=True)

    class Meta:
        model = FeatureFlag
        fields = (
            'id', 'key', 'name', 'description', 'status', 'rollout_strategy',
            'rollout_percentage', 'target_users', 'target_tenants',
            'target_user_count', 'target_tenant_count',
            'starts_at', 'ends_at', 'metadata',
            'created_by', 'created_by_name', 'updated_by', 'updated_by_name',
            'created_at', 'updated_at',
        )
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'updated_by']
        extra_kwargs = {'key': {'validators': []}}

    def validate_key(self, value):
        qs = FeatureFlag.objects.filter(key=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'特性键：{value}当前已存在')
        return value


class FeatureFlagBriefSerializer(serializers.ModelSerializer):
    """特性开关摘要序列化器（用于列表展示）"""
    class Meta:
        model = FeatureFlag
        fields = ('id', 'key', 'name', 'status', 'rollout_strategy', 'rollout_percentage', 'created_at')


class ConfigHistorySerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.username', read_only=True, default='')

    class Meta:
        model = ConfigHistory
        fields = (
            'id', 'config_key', 'config_type', 'operation', 'old_value',
            'new_value', 'diff', 'operator', 'operator_name', 'created_at',
        )
        read_only_fields = ['id', 'created_at']
