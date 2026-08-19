from rest_framework import serializers
from .models import AuditLog

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
