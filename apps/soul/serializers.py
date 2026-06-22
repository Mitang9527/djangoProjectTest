from rest_framework import serializers
from .models import Soul

class SoulSerializer(serializers.ModelSerializer):
    """Soul 序列化器"""
    class Meta:
        model = Soul
        fields = '__all__'

class SoulTestSerializer(serializers.Serializer):
    """Soul 测试接口序列化器"""
    info = serializers.CharField(max_length=100, help_text="测试信息")
    timestamp = serializers.DateTimeField(help_text="时间戳")
