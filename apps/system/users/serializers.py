from rest_framework import serializers
from django.apps import apps
from django.contrib.auth import get_user_model, authenticate
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema_field

User = get_user_model()

class RoleSerializer(serializers.ModelSerializer):
    """角色序列化器"""
    class Meta:
        model = None
        fields = ('id', 'name', 'slug', 'description', 'is_system', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.Meta.model is None:
            self.Meta.model = apps.get_model('saas', 'Role')

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
        
        # 为新用户自动分配默认的普通成员角色
        try:
            Role = apps.get_model('saas', 'Role')
            default_role = Role.objects.filter(slug='member', tenant__isnull=True, is_active=True).first()
            if default_role:
                user.role = default_role
                user.save(update_fields=['role'])
        except Exception as e:
            # 如果获取默认角色失败也不影响用户创建
            pass
            
        return user

class UserDetailSerializer(serializers.ModelSerializer):
    """用户详情序列化器"""
    role_info = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'nickname', 'mobile', 'avatar', 'role', 'role_info', 'date_joined')
        read_only_fields = ('id', 'username', 'date_joined')
    
    @extend_schema_field(dict)
    def get_role_info(self, obj):
        if obj.role:
            return {
                'id': str(obj.role.id),
                'name': obj.role.name,
                'slug': obj.role.slug,
                'description': obj.role.description,
                'is_system': obj.role.is_system,
                'is_active': obj.role.is_active
            }
        return None

class UserLoginSerializer(serializers.Serializer):
    """用户登录序列化器：仅验证基础格式"""
    username = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, required=True)

class TestApiSerializer(serializers.Serializer):
    """测试接口序列化器"""
    msg = serializers.CharField(max_length=100, help_text="发送的消息内容")
    status = serializers.BooleanField(default=True, help_text="状态标识")

def resolve_login_tenant(request, user) -> str | None:
    """
    登录时解析要写入 JWT 的 tenant_id（多租户上下文 claim）。

    优先级：
      1) 请求体显式携带 tenant_id / tenantId（必须已是该租户活跃成员）；
      2) 否则取用户首个「活跃」租户成员关系；
      3) 无成员关系（如超管 / 系统用户）返回 None。

    仅在函数内惰性导入 saas 模型，避免模块加载期循环依赖。
    """
    from apps.system.saas.models import TenantMember

    if request is not None:
        try:
            body = request.data or {}
        except Exception:
            body = {}
        tid = body.get('tenant_id') or body.get('tenantId')
        if tid and TenantMember.objects.filter(
            tenant_id=tid, user=user, is_active=True
        ).exists():
            return str(tid)

    member = (
        TenantMember.objects
        .filter(user=user, is_active=True, tenant__status='active')
        .order_by('joined_at')
        .first()
    )
    return str(member.tenant_id) if member else None


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """自定义 JWT Token 序列化器，添加用户信息"""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # 添加自定义声明
        token['username'] = user.username
        token['role_id'] = str(user.role.id) if user.role else None
        token['email'] = user.email

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # 注入多租户上下文 claim：重新解码 refresh 并补 tenant_id，
        # 再重建 access（simplejwt 刷新时会自动将该 claim 复制到新 access）。
        request = self.context.get('request')
        tenant_id = resolve_login_tenant(request, self.user)
        if tenant_id:
            refresh = RefreshToken(data['refresh'])
            refresh['tenant_id'] = tenant_id
            data['refresh'] = str(refresh)
            data['access'] = str(refresh.access_token)

        # 添加用户信息到响应
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'nickname': getattr(self.user, 'nickname', ''),
            'role_id': str(self.user.role.id) if self.user.role else None,
            'role_name': self.user.role.name if self.user.role else None,
            'tenant_id': tenant_id,
        }

        return data

class RefreshTokenSerializer(serializers.Serializer):
    """刷新 Token 序列化器"""
    refresh = serializers.CharField(required=True, help_text="刷新 Token")

class UserManageSerializer(serializers.ModelSerializer):
    """管理员操作用户的序列化器（创建/编辑/删除）"""
    password = serializers.CharField(write_only=True, min_length=6, required=False, label="密码")
    role_info = serializers.SerializerMethodField()
    role_id = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'email', 'nickname', 'mobile', 'role', 'role_info', 'role_id', 'is_active', 'date_joined')
        read_only_fields = ('id', 'date_joined', 'role')
        extra_kwargs = {
            'username': {'validators': [UniqueValidator(queryset=User.objects.all(), message="用户名已存在")]},
            'email': {'required': True, 'validators': [UniqueValidator(queryset=User.objects.all(), message="该邮箱已被注册")]},
            'mobile': {'required': False, 'allow_blank': True, 'validators': [UniqueValidator(queryset=User.objects.all(), message="该手机号已被注册")]},
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['role'] = str(instance.role.id) if instance.role else None
        return data

    def to_internal_value(self, data):
        # 兼容处理：如果提供了 role 字段，将其复制到 role_id
        if 'role' in data and 'role_id' not in data:
            data = data.copy()
            data['role_id'] = data['role']
        return super().to_internal_value(data)
    
    def validate_role_id(self, value):
        if not value or value == '':
            return None
        try:
            import uuid
            uuid.UUID(str(value))
        except (ValueError, TypeError):
            raise serializers.ValidationError("角色ID必须是有效的UUID格式")
        return value
    
    def create(self, validated_data):
        role_id = validated_data.pop('role_id', None)
        password = validated_data.pop('password', None)
        if not validated_data.get('mobile'):
            validated_data['mobile'] = None
        user = User.objects.create_user(**validated_data)
        
        # 处理角色关联
        if role_id:
            Role = apps.get_model('saas', 'Role')
            try:
                role = Role.objects.get(id=role_id)
                user.role = role
                user.save(update_fields=['role'])
            except Role.DoesNotExist:
                pass
        
        if password:
            user.set_password(password)
            user.save(update_fields=['password'])
        return user

    def update(self, instance, validated_data):
        role_id = validated_data.pop('role_id', None)
        password = validated_data.pop('password', None)
        if not validated_data.get('mobile', instance.mobile):
            validated_data['mobile'] = None
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # 处理角色关联
        if role_id is not None:  # 允许显式设置为 None
            if role_id:
                Role = apps.get_model('saas', 'Role')
                try:
                    role = Role.objects.get(id=role_id)
                    instance.role = role
                except Role.DoesNotExist:
                    instance.role = None
            else:
                instance.role = None
        
        if password:
            instance.set_password(password)
        instance.save()
        return instance
    
    @extend_schema_field(dict)
    def get_role_info(self, obj):
        if obj.role:
            return {
                'id': str(obj.role.id),
                'name': obj.role.name,
                'slug': obj.role.slug,
                'description': obj.role.description,
                'is_system': obj.role.is_system,
                'is_active': obj.role.is_active
            }
        return None

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


class LogoutSerializer(serializers.Serializer):
    """登出序列化器"""
    refresh = serializers.CharField(required=True, help_text="刷新 Token")

