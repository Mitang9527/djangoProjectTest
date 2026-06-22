from rest_framework import serializers
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

class LogoutSerializer(serializers.Serializer):
    """登出序列化器"""
    refresh = serializers.CharField(required=True, help_text="刷新 Token")

