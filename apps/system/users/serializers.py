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
        # mobile 空串→None
        if not validated_data.get('mobile'):
            validated_data['mobile'] = None
            
        user = User.objects.create_user(**validated_data)
        
        # 分配默认普通成员角色
        try:
            Role = apps.get_model('saas', 'Role')
            default_role = Role.objects.filter(slug='member', tenant__isnull=True, is_active=True).first()
            if default_role:
                user.role = default_role
                user.save(update_fields=['role'])
        except Exception as e:
            # 默认角色获取失败不影响创建
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
    mfa_code = serializers.CharField(
        required=False, allow_blank=True, write_only=True,
        help_text="MFA 二次验证码（TOTP 6 位或恢复码），用户启用 MFA 后必填",
    )

class TestApiSerializer(serializers.Serializer):
    """测试接口序列化器"""
    msg = serializers.CharField(max_length=100, help_text="发送的消息内容")
    status = serializers.BooleanField(default=True, help_text="状态标识")

def resolve_login_tenant(request, user) -> str | None:
    """登录时解析要写入 JWT 的 tenant_id（多租户上下文 claim）。
    优先级：1)请求体 tenant_id/tenantId（须是活跃成员）→ 2)is_default=True 默认租户 → 3)首个活跃成员 → 4)无则 None。
    惰性导入 saas 模型避免循环依赖。
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


def create_user_session(user, access_token, tenant_id=None, request=None,
                        notify_new_device=False):
    """签发 access token 后统一写入会话记录（jti 绑定 user+tenant，供认证层校验）。
    Args: user; access_token(须已生成 jti); tenant_id; request(记录 IP/UA);
         notify_new_device: 登录类签发点 True（新设备提醒），刷新/切租户/改密重签保持 False。
    Returns: UserSession | None（无 jti 返回 None，不阻断签发）。
    """
    from system.users.models import UserSession

    # 注意：Token 无迭代协议，须用 .payload（dict(token) 会 KeyError）
    payload = access_token.payload
    jti = payload.get('jti')
    if not jti:
        return None

    exp = payload.get('exp')
    exp_dt = None
    if isinstance(exp, (int, float)):
        # Django 5.2 移除 django.utils.timezone.utc，改用标准库 timezone.utc
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

    session = UserSession.objects.create(
        user=user,
        tenant_id=tenant_id,
        token_jti=jti,
        ip=ip,
        user_agent=ua,
        expires_at=exp_dt,
    )
    # 新设备（IP+UA 首次出现）站内信提醒（best-effort）
    if notify_new_device:
        from system.users.login_security import maybe_notify_new_device_login

        maybe_notify_new_device_login(user, session, request)
    return session


def attach_tenant_claim(token, request, user) -> str | None:
    """把登录时解析到的默认租户写入 JWT claim，供全部 JWT 签发点统一调用。
    无租户上下文返回 None 不写 claim；调用方可把返回值同步进登录响应供前端感知默认租户。
    """
    tenant_id = resolve_login_tenant(request, user)
    if tenant_id:
        token['tenant_id'] = tenant_id
    return tenant_id


def issue_login_tokens(user, request=None, notify_new_device=True) -> dict:
    """统一 JWT 签发链（登录类签发点收敛于此，避免各端点复制逻辑）。
    流程：RefreshToken.for_user → token_version 自增写 claim（单设备语义）→ 租户 claim → access 实例复用（jti 与会话一致）→ 会话记录 → 登录日志。
    Args: user; request(租户/IP/UA/日志); notify_new_device(登录类 True，非登录路径 False)。Returns: {"access","refresh"}。
    """
    from rest_framework_simplejwt.tokens import RefreshToken

    from system.core.audit import record_login_log

    refresh = RefreshToken.for_user(user)
    # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
    if hasattr(user, "token_version"):
        user.token_version = (user.token_version or 0) + 1
        user.save(update_fields=["token_version"])
        refresh["token_version"] = user.token_version
    # 多租户 claim：默认租户
    tenant_id = attach_tenant_claim(refresh, request, user)
    # 先取 access 实例复用（jti 与会话一致）
    access = refresh.access_token
    tokens = {"access": str(access), "refresh": str(refresh)}
    # 会话记录（jti 绑定 user+tenant）：切租户/登出吊销后旧 access 失效
    create_user_session(user, access, tenant_id, request, notify_new_device=notify_new_device)
    record_login_log(
        email=user.email or user.username, status='success',
        user=user, tenant_id=tenant_id, request=request,
    )
    return tokens


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """自定义 JWT Token 序列化器，添加用户信息 + MFA 二次验证"""

    mfa_code = serializers.CharField(
        required=False, allow_blank=True, write_only=True,
        help_text="MFA 二次验证码（TOTP 6 位或恢复码），用户启用 MFA 后必填",
    )

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

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
        try:
            # 父类在此生成 refresh/access；认证失败抛 AuthenticationFailed
            data = super().validate(attrs)
        except Exception as e:
            from system.core.audit import record_login_log
            from framework.gateway.login_throttle import LoginThrottleService
            username = attrs.get(self.username_field, '') or ''
            # 登录失败计数（IP+用户名双维度，防暴力破解）
            LoginThrottleService.record_failed_login_attempt(
                self.context.get('request'), username)
            record_login_log(
                email=username,
                status='failed', request=self.context.get('request'),
                failure_reason='bad_credentials',
            )
            raise e

        # MFA 校验：启用 MFA 须携带 mfa_code；失败计入限流；此时 self.user 必然存在
        from system.users.services import verify_mfa_for_login
        mfa_ok, mfa_reason = verify_mfa_for_login(self.user, attrs.get('mfa_code'))
        if not mfa_ok:
            from rest_framework_simplejwt.exceptions import AuthenticationFailed
            from framework.gateway.login_throttle import LoginThrottleService
            from system.core.audit import record_login_log

            LoginThrottleService.record_failed_login_attempt(
                self.context.get('request'), self.user.username)
            record_login_log(
                email=self.user.email or self.user.username, status='failed',
                request=self.context.get('request'),
                failure_reason='mfa_failed',
            )
            raise AuthenticationFailed({
                "detail": "需要二次验证" if mfa_reason == "mfa_required" else "二次验证失败",
                "code": mfa_reason,  # 'mfa_required' | 'mfa_failed'
            })

        # 多租户 claim 写入 refresh（simplejwt 刷新时自动复制到新 access）
        request = self.context.get('request')
        refresh = RefreshToken(data['refresh'])
        tenant_id = attach_tenant_claim(refresh, request, self.user)
        # 注意：先取 access 实例复用并重写，保证会话记录 jti 与 access 一致
        access = refresh.access_token
        data['refresh'] = str(refresh)
        data['access'] = str(access)

        # 会话记录（jti 绑定 user+tenant）：切租户/登出吊销后旧 access 失效
        create_user_session(self.user, access, tenant_id, request, notify_new_device=True)

        from system.core.audit import record_login_log
        record_login_log(
            email=self.user.email or self.user.username, status='success',
            user=self.user, tenant_id=tenant_id, request=request,
        )

        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'nickname': getattr(self.user, 'nickname', ''),
            'role_id': str(self.user.role.id) if self.user.role else None,
            'role_name': self.user.role.name if self.user.role else None,
            'tenant_id': tenant_id,
        }

        # 成功清零 IP/用户名双维度计数
        from framework.gateway.login_throttle import LoginThrottleService
        LoginThrottleService.clear_failed_login_attempts(request, self.user.username)

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

        # 新 access 写会话记录（新 jti），旧 refresh 已 blacklist
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
        # 兼容：提供 role 字段则复制到 role_id
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
    """v2 用户管理序列化器：继承 v1 仅增加 version 字段，鉴权/过滤/权限逻辑全部复用 v1（版本迭代只重写差异范例）。"""
    version = serializers.SerializerMethodField()

    class Meta(UserManageSerializer.Meta):
        fields = UserManageSerializer.Meta.fields + ('version',)

    def get_version(self, obj):
        return 'v2'


# MFA 双因子认证序列化器（对齐 Fast-Vben-Admin core/mfa.py）

class MfaSetupSerializer(serializers.Serializer):
    """生成 MFA 绑定：已启用用户须提供当前 TOTP 或恢复码（防劫持换绑）"""
    mfa_code = serializers.CharField(
        required=False, allow_blank=True, write_only=True,
        help_text="当前 MFA 验证码（TOTP 6 位或恢复码），仅已启用 MFA 的用户必填",
    )


class MfaConfirmSerializer(serializers.Serializer):
    """确认绑定：提交 Authenticator App 中的 6 位 TOTP 码"""
    code = serializers.CharField(required=True, write_only=True, help_text="6 位 TOTP 验证码")


class MfaDisableSerializer(serializers.Serializer):
    """禁用 MFA：提交 TOTP 码或恢复码任一验证通过即可"""
    code = serializers.CharField(required=True, write_only=True, help_text="TOTP 6 位验证码或恢复码")


class MfaRecoverySerializer(serializers.Serializer):
    """重新生成恢复码：须提交 6 位 TOTP 验证码（确认仍持有 Authenticator）"""
    code = serializers.CharField(required=True, write_only=True, help_text="6 位 TOTP 验证码")

