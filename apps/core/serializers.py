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
        fields = '__all__'

class SystemStatusSerializer(serializers.Serializer):
    """
    系统状态序列化器
    """
    cpu_usage = serializers.FloatField()
    mem_usage = serializers.FloatField()
    active_users = serializers.IntegerField()
    last_update = serializers.CharField()
