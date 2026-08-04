"""AI 创作工作室 - DRF 序列化器"""
from rest_framework import serializers
from .models import GenerationTask, UserQuota


class GenerationCreateSerializer(serializers.Serializer):
    """创建生成任务的入参校验"""

    kind = serializers.ChoiceField(choices=["image", "video"], default="image")
    prompt = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    ref_image = serializers.CharField(required=False, allow_blank=True)
    style = serializers.CharField(required=False, allow_blank=True, max_length=30)
    size = serializers.CharField(required=False, allow_blank=True, max_length=10)
    resolution = serializers.ChoiceField(choices=["standard", "hd", "4k"], default="standard")
    count = serializers.IntegerField(min_value=1, max_value=8, default=1)


class GenerationTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationTask
        fields = [
            "id", "kind", "prompt", "style", "size", "resolution", "count",
            "cost", "status", "result_urls", "error_msg", "created_at", "finished_at",
        ]


class QuotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserQuota
        fields = ["balance", "frozen", "total_granted"]
