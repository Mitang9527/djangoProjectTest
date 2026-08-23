from rest_framework import serializers
from django.utils import timezone
from .models import AuditLog, APIKey

class AuditLogSerializer(serializers.ModelSerializer):
    """
    审计日志序列化器
    """
    user_name = serializers.CharField(source='user.username', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            'id', 'user', 'user_name', 'action', 'action_display', 'log_type',
            'target_model', 'target_id', 'old_data', 'new_data', 'changes',
            'action_info', 'ip_address', 'user_agent', 'request_path',
            'request_method', 'data_hash', 'previous_hash', 'is_tampered', 'created_at',
        )
        read_only_fields = [
            'id', 'data_hash', 'previous_hash', 'is_tampered', 'created_at',
        ]

class SystemStatusSerializer(serializers.Serializer):
    """
    系统状态序列化器
    """
    cpu_usage = serializers.FloatField()
    mem_usage = serializers.FloatField()
    active_users = serializers.IntegerField()
    last_update = serializers.CharField()


class PingSerializer(serializers.Serializer):
    """
    连通性测试 POST 参数校验器
    """
    name = serializers.CharField(max_length=50, help_text="你的名字，将用于回显问候")


class CreateApiKeySerializer(serializers.Serializer):
    """
    签发 API Key 入参校验器（接口版，等价于 manage.py create_api_key）。
    """
    name = serializers.CharField(
        max_length=100,
        help_text="密钥用途标识，例如：报表导出服务",
    )
    owner_username = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="归属用户名；省略则归属当前调用者。仅管理员可指定他人。",
    )
    ttl = serializers.IntegerField(
        required=False,
        default=3600,
        min_value=0,
        help_text="有效秒数；0 表示永不过期",
    )


class ApiKeySerializer(serializers.ModelSerializer):
    """
    API Key 列表 / 详情序列化器。

    安全约束：
    - 绝不输出明文 ``key`` 与 ``key_hash``；
    - ``masked_key`` 仅展示前缀与末 4 位；
    - 可写字段仅 ``name``（改名）与 ``is_active``（吊销 / 重新启用），
      其余字段只读。
    """

    masked_key = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_usable = serializers.SerializerMethodField()
    remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = APIKey
        fields = (
            "id", "name", "masked_key",
            "user_id", "user_username",
            "is_active", "is_expired", "is_usable",
            "expires_at", "last_used_at", "remaining_seconds",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "masked_key", "user_id", "user_username",
            "is_expired", "is_usable", "expires_at", "last_used_at",
            "remaining_seconds", "created_at", "updated_at",
        )

    def get_masked_key(self, obj) -> str:
        return obj.masked_key

    def get_is_expired(self, obj) -> bool:
        return obj.is_expired()

    def get_is_usable(self, obj) -> bool:
        return obj.is_usable()

    def get_remaining_seconds(self, obj) -> int | None:
        if not obj.expires_at:
            return None
        return max(int((obj.expires_at - timezone.now()).total_seconds()), 0)
