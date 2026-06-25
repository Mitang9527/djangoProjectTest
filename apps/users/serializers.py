from rest_framework import serializers
from django.apps import apps
from django.contrib.auth import get_user_model, authenticate
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

class UserRegisterSerializer(serializers.ModelSerializer):
    """用户注册序列化器"""
    password = serializers.CharField(write_only=True, min_length=6, max_length=20, label="密码")
    password_confirm = serializers.CharField(write_only=True, min_length=6, max_length=20, label="确认密码")
    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="该邮箱已被注册")]
    )
    mobile = serializers.CharField(
        required=False, 
        allow_blank=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="该手机号已被注册")]
    )

    class Meta:
        model = User
        fields = ('username', 'password', 'password_confirm', 'email', 'nickname', 'mobile')
        extra_kwargs = {
            'username': {
                'validators': [UniqueValidator(queryset=User.objects.all(), message="用户名已存在")]
            },
            'nickname': {'required': False, 'allow_blank': True},
        }

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"两次输入的密码不一致"})
        return data

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        # 处理 mobile 为空字符串的情况，存入数据库应为 None
        if not validated_data.get('mobile'):
            validated_data['mobile'] = None
            
        user = User.objects.create_user(**validated_data)
        return user

class UserDetailSerializer(serializers.ModelSerializer):
    """用户详情序列化器"""
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'nickname', 'mobile', 'avatar', 'token', 'role', 'date_joined')
        read_only_fields = ('id', 'username', 'token', 'date_joined')

class UserLoginSerializer(serializers.Serializer):
    """用户登录序列化器：仅验证基础格式"""
    username = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, required=True)

class TestApiSerializer(serializers.Serializer):
    """测试接口序列化器"""
    msg = serializers.CharField(max_length=100, help_text="发送的消息内容")
    status = serializers.BooleanField(default=True, help_text="状态标识")

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """自定义 JWT Token 序列化器，添加用户信息"""
    
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        
        # 添加自定义声明
        token['username'] = user.username
        token['role'] = getattr(user, 'role', 'user')
        token['email'] = user.email
        
        return token
    
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # 添加用户信息到响应
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'nickname': getattr(self.user, 'nickname', ''),
            'role': getattr(self.user, 'role', 'user'),
        }
        
        return data

class RefreshTokenSerializer(serializers.Serializer):
    """刷新 Token 序列化器"""
    refresh = serializers.CharField(required=True, help_text="刷新 Token")

class UserManageSerializer(serializers.ModelSerializer):
    """管理员操作用户的序列化器（创建/编辑/删除）

    创建时可选 initial_tenant_id + initial_role_id 一步完成用户创建和角色分配。
    """
    password = serializers.CharField(write_only=True, min_length=6, required=False, label="密码")
    tenant_memberships = serializers.SerializerMethodField(label="租户角色")

    # —— 创建用户时一步分配租户角色 ——
    initial_tenant_id = serializers.UUIDField(write_only=True, required=False, allow_null=True, label="初始租户")
    initial_role_id = serializers.UUIDField(write_only=True, required=False, allow_null=True, label="初始角色")

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'email', 'nickname', 'mobile', 'role',
                  'is_active', 'date_joined', 'tenant_memberships',
                  'initial_tenant_id', 'initial_role_id')
        read_only_fields = ('id', 'date_joined', 'tenant_memberships')
        extra_kwargs = {
            'username': {'validators': [UniqueValidator(queryset=User.objects.all(), message="用户名已存在")]},
            'email': {'required': True, 'validators': [UniqueValidator(queryset=User.objects.all(), message="该邮箱已被注册")]},
            'mobile': {'required': False, 'allow_blank': True, 'validators': [UniqueValidator(queryset=User.objects.all(), message="该手机号已被注册")]},
        }

    def get_tenant_memberships(self, obj):
        """返回用户在各租户中的角色信息"""
        memberships = obj.tenant_memberships.select_related('tenant', 'role').all()
        return [
            {
                'tenant_id': str(m.tenant_id),
                'tenant_name': m.tenant.name,
                'role_id': str(m.role_id) if m.role_id else None,
                'role_name': m.role.name if m.role else '---',
                'role_slug': m.role.slug if m.role else '',
            }
            for m in memberships
        ]

    def validate_username(self, value):
        qs = User.objects.filter(username=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'用户名：{value}当前已存在')
        return value

    def validate_email(self, value):
        qs = User.objects.filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'邮箱：{value}当前已存在')
        return value

    def validate_mobile(self, value):
        if not value:
            return value
        qs = User.objects.filter(mobile=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f'手机号：{value}当前已存在')
        return value

    def validate(self, data):
        """创建用户时角色必选；若提供了租户则需与角色匹配"""
        if self.instance is None:  # 仅创建时校验
            role_id = data.get('initial_role_id')
            tenant_id = data.get('initial_tenant_id')
            if not role_id:
                raise serializers.ValidationError({'initial_role_id': '角色为必选项'})
            if tenant_id and role_id:
                # 验证角色属于该租户
                Role = apps.get_model('saas', 'Role')
                if not Role.objects.filter(id=role_id, tenant_id=tenant_id, is_active=True).exists():
                    raise serializers.ValidationError({'initial_role_id': '所选角色不属于该租户'})
        return data

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        tenant_id = validated_data.pop('initial_tenant_id', None)
        role_id = validated_data.pop('initial_role_id', None)

        if not validated_data.get('mobile'):
            validated_data['mobile'] = None

        user = User.objects.create_user(**validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=['password'])

        # 创建用户时一步分配租户角色
        if role_id:
            Tenant = apps.get_model('saas', 'Tenant')
            Role = apps.get_model('saas', 'Role')
            TenantMember = apps.get_model('saas', 'TenantMember')
            try:
                role = Role.objects.select_related('tenant').get(id=role_id, is_active=True)

                # 确定租户：明确指定 > 从角色推断
                if tenant_id:
                    tenant = Tenant.objects.get(id=tenant_id, status='active')
                elif role.tenant_id:
                    tenant = role.tenant
                else:
                    # 角色没有绑定租户（全局角色），无法创建 TenantMember，跳过
                    tenant = None

                if tenant:
                    TenantMember.objects.create(
                        tenant=tenant, user=user, role=role,
                        invited_by=self.context['request'].user if 'request' in self.context else None
                    )
                # 角色无租户绑定（全局系统角色）→ 跳过 TenantMember 创建，仅记录系统角色
            except (Tenant.DoesNotExist, Role.DoesNotExist):
                pass  # 静默跳过无效的租户/角色，不影响用户创建

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if not validated_data.get('mobile', instance.mobile):
            validated_data['mobile'] = None
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class LogoutSerializer(serializers.Serializer):
    """登出序列化器"""
    refresh = serializers.CharField(required=True, help_text="刷新 Token")

