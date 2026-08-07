"""AI 创作工作室 - DRF 序列化器"""
from rest_framework import serializers
from .models import GenerationTask, UserQuota, ApiChannel, UserChannelGrant


class GenerationCreateSerializer(serializers.Serializer):
    """创建生成任务的入参校验"""

    kind = serializers.ChoiceField(choices=['image', 'video'], default='image')
    prompt = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    ref_image = serializers.CharField(required=False, allow_blank=True)
    style = serializers.CharField(required=False, allow_blank=True, max_length=30)
    size = serializers.CharField(required=False, allow_blank=True, max_length=10)
    resolution = serializers.ChoiceField(choices=['standard', 'hd', '4k'], default='standard')
    count = serializers.IntegerField(min_value=1, max_value=8, default=1)


class GenerationTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationTask
        fields = [
            'id', 'kind', 'prompt', 'style', 'size', 'resolution', 'count',
            'cost', 'status', 'result_urls', 'error_msg', 'created_at', 'finished_at',
        ]


class QuotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserQuota
        fields = ['balance', 'frozen', 'total_granted']


class RechargeSerializer(serializers.Serializer):
    """提交充值订单的入参"""

    amount = serializers.IntegerField(min_value=1, max_value=1000000)
    method = serializers.CharField(required=False, default='mock', max_length=20)


class AdminGrantSerializer(serializers.Serializer):
    """管理员发放/扣减额度的入参"""

    user_id = serializers.IntegerField(required=False)
    username = serializers.CharField(required=False)
    amount = serializers.IntegerField()  # 负数表示扣减
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ChannelSerializer(serializers.ModelSerializer):
    """渠道/Agent 完整信息（管理员后台使用，含 config）"""

    class Meta:
        model = ApiChannel
        fields = [
            'id', 'name', 'kind', 'is_active', 'description',
            'cost_per_call', 'config', 'created_at', 'updated_at',
        ]


class ChannelCreateSerializer(serializers.ModelSerializer):
    """创建/更新渠道的入参"""

    class Meta:
        model = ApiChannel
        fields = ['name', 'kind', 'description', 'cost_per_call', 'config', 'is_active']


class MyChannelSerializer(serializers.ModelSerializer):
    """普通用户可见的渠道信息（功能入口用，不含敏感 config）"""

    class Meta:
        model = ApiChannel
        fields = ['id', 'name', 'kind', 'description', 'cost_per_call']


class GrantSerializer(serializers.ModelSerializer):
    """用户-渠道授权记录"""

    username = serializers.CharField(source='user.username', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)

    class Meta:
        model = UserChannelGrant
        fields = [
            'id', 'user', 'username', 'channel', 'channel_name',
            'enabled', 'per_user_quota', 'used_quota', 'granted_at',
        ]
        read_only_fields = ['id', 'used_quota', 'granted_at']


class GrantWriteSerializer(serializers.Serializer):
    """管理员设置某用户对某渠道的授权（upsert）"""

    user_id = serializers.IntegerField(required=False)
    username = serializers.CharField(required=False)
    channel_id = serializers.IntegerField()
    enabled = serializers.BooleanField(default=True)
    per_user_quota = serializers.IntegerField(required=False, allow_null=True)
