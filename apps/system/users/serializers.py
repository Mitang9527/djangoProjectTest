from datetime import datetime as _dt, timezone as _dt_tz

from rest_framework import serializers
from django.apps import apps
from django.contrib.auth import get_user_model, authenticate
from django.utils import timezone
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
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

    优先级（对齐参考项目 is_default 语义）：
      1) 请求体显式携带 tenant_id / tenantId（必须已是该租户活跃成员）；
      2) 否则取用户「is_default=True」的活跃成员关系（默认租户）；
      3) 再否则取首个活跃成员关系；
      4) 无成员关系（如超管 / 系统用户）返回 None。

    仅在函数内惰性导入 saas 模型，避免模块加载期循环依赖。
    """
    from system.saas.models import TenantMember

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
        .order_by('-is_default', 'joined_at')
        .first()
    )
    return str(member.tenant_id) if member else None


def create_user_session(user, access_token, tenant_id=None, request=None):
    """
    签发 access token 后统一写入会话记录（效仿参考项目 create_login_token）。

    会话以 token_jti 绑定 user + tenant，供认证层校验：
      - 切租户 / 登出时吊销对应 jti 会话 → 该 access 立即失效；
      - 会话记录存在则强制校验（revoked 即拒绝），记录不存在（存量旧 token）放行。

    Args:
        user: 用户对象
        access_token: simplejwt AccessToken（须已生成 jti；新 token 默认自动生成）
        tenant_id: 租户 ID 字符串 / UUID / None
        request: 可选，用于记录 IP 与 User-Agent

    Returns:
        UserSession | None（无 jti 时返回 None，不阻断签发）
    """
    from system.users.models import UserSession

    # 注意：simplejwt Token 无迭代协议，须用 .payload（dict(AccessToken) 会 KeyError）
    payload = access_token.payload
    jti = payload.get('jti')
    if not jti:
        return None

    exp = payload.get('exp')
    exp_dt = None
    if isinstance(exp, (int, float)):
        # Django 5.2 已移除 django.utils.timezone.utc，用标准库 timezone.utc
        exp_dt = _dt.fromtimestamp(exp, tz=_dt_tz.utc)
    elif isinstance(exp, timezone.datetime):
        exp_dt = exp

    ip = ''
    ua = ''
    if request is not None:
        try:
            ip = request.META.get('HTTP_X_FORWARDED_FOR', '') or request.META.get('REMOTE_ADDR', '')
            ip = ip.split(',')[0].strip()[:64]
            ua = request.META.get('HTTP_USER_AGENT', '')[:512]
        except Exception:
            pass

    return UserSession.objects.create(
        user=user,
        tenant_id=tenant_id,
        token_jti=jti,
        ip=ip,
        user_agent=ua,
        expires_at=exp_dt,
    )


def attach_tenant_claim(token, request, user) -> str | None:
    """
    把登录时解析到的默认租户写入 JWT claim（多租户上下文）。

    供全部 JWT 签发点（标准登录 / DemoLogin / OIDC / LoginService /
    TokenService）统一调用，避免各自重复解析逻辑。
    - 无租户上下文（系统超管 / 新用户暂无成员关系）时返回 None，不写 claim；
    - 调用方可用返回值把 tenant_id 同步放进登录响应，供前端感知默认租户。
    """
    tenant_id = resolve_login_tenant(request, user)
    if tenant_id:
        token['tenant_id'] = tenant_id
    return tenant_id


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """自定义 JWT Token 序列化器，添加用户信息"""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # 添加自定义声明
        # 注入自定义 claims 到 token
        token['username'] = user.username
        token['role_id'] = str(user.role.id) if user.role else None
        token['email'] = user.email

        # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
        if hasattr(user, 'token_version'):
            user.token_version = (user.token_version or 0) + 1
            user.save(update_fields=['token_version'])
            token['token_version'] = user.token_version

        return token

    def validate(self, attrs):
        # 生成 refresh/access + 拼 data.user
        data = super().validate(attrs)      # SimpleJWT 父类在此生成 refresh/access

        # 注入多租户上下文 claim：把默认租户写入 refresh（simplejwt 刷新时
        # 会自动将该 claim 复制到新 access）。
        request = self.context.get('request')
        refresh = RefreshToken(data['refresh'])
        tenant_id = attach_tenant_claim(refresh, request, self.user)
        # 注意：refresh.access_token 每次访问都新建实例（新 jti），先取实例复用，
        # 并始终用该实例重写 access/refresh，保证与下面会话记录的 jti 一致。
        access = refresh.access_token
        data['refresh'] = str(refresh)
        data['access'] = str(access)

        # 写入会话记录（jti 绑定 user+tenant）：切租户 / 登出吊销后旧 access 立即失效
        create_user_session(self.user, access, tenant_id, request)

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

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])

        if jwt_api_settings.ROTATE_REFRESH_TOKENS:
            if jwt_api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()

        # 新 access 写入会话记录（新 jti），旧 refresh 已 blacklist
        access = refresh.access_token
        data = {"access": str(access)}
        if jwt_api_settings.ROTATE_REFRESH_TOKENS:
            data["refresh"] = str(refresh)

        user_id = refresh.payload.get(jwt_api_settings.USER_ID_CLAIM)
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                user = None
            if user is not None:
                create_user_session(
                    user, access,
                    refresh.payload.get('tenant_id'),
                    self.context.get('request'),
                )

        return data

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
            # 改密后使该用户所有旧 token 立即失效
            instance.token_version = (instance.token_version or 0) + 1
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


class UserManageSerializerV2(UserManageSerializer):
    """
    v2 用户管理序列化器：继承 v1（UserManageSerializer），仅增加 version 标记字段，
    作为「版本迭代只重写差异」的范例。鉴权 / 过滤 / 权限逻辑全部复用 v1。
    """
    version = serializers.SerializerMethodField()

    class Meta(UserManageSerializer.Meta):
        fields = UserManageSerializer.Meta.fields + ('version',)

    def get_version(self, obj):
        return 'v2'

