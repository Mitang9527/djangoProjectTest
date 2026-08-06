"""
告警系统 — DRF 序列化器

4 个模型的 ModelSerializer + 业务 action 序列化器（确认/解决/触发/测试通知）。
"""

from rest_framework import serializers

from .models import (
    AlertRule,
    AlertSilence,
    AlertHistory,
    AlertNotificationConfig,
    AlertChannel,
    AlertLevel,
    AlertStatus,
)


# ---------------------------------------------------------------
# Model Serializers
# ---------------------------------------------------------------

class AlertRuleSerializer(serializers.ModelSerializer):
    """告警规则"""

    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    level_display = serializers.CharField(source="get_level_display", read_only=True)
    condition_type_display = serializers.CharField(
        source="get_condition_type_display", read_only=True
    )

    class Meta:
        model = AlertRule
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "level",
            "level_display",
            "condition_type",
            "condition_type_display",
            "condition_value",
            "channels",
            "escalation_rules",
            "silent_periods",
            "suppression_window",
            "max_occurrences",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]

    def validate_channels(self, value):
        """校验通知渠道列表"""
        if not isinstance(value, list):
            raise serializers.ValidationError("channels 必须是数组")
        valid = {c[0] for c in AlertChannel.choices}
        for ch in value:
            if ch not in valid:
                raise serializers.ValidationError(
                    f"无效的渠道 '{ch}'，可选值: {', '.join(valid)}"
                )
        return value

    def validate_silent_periods(self, value):
        """校验静默时段格式"""
        if not value:
            return value
        if not isinstance(value, list):
            raise serializers.ValidationError("silent_periods 必须是数组")
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("每个静默时段必须是对象")
            if "start" not in item or "end" not in item:
                raise serializers.ValidationError("静默时段必须包含 start 和 end")
        return value

    def validate_escalation_rules(self, value):
        """校验升级规则格式"""
        if not value:
            return value
        if not isinstance(value, list):
            raise serializers.ValidationError("escalation_rules 必须是数组")
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("每条升级规则必须是对象")
            if "delay_minutes" not in item:
                raise serializers.ValidationError("升级规则必须包含 delay_minutes")
        return value


class AlertSilenceSerializer(serializers.ModelSerializer):
    """告警静默"""

    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    rule_name = serializers.CharField(source="rule.name", read_only=True)

    class Meta:
        model = AlertSilence
        fields = [
            "id",
            "name",
            "description",
            "rule",
            "rule_name",
            "match_pattern",
            "start_time",
            "end_time",
            "enabled",
            "is_active",
            "created_at",
            "created_by",
            "created_by_name",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate(self, attrs):
        """结束时间必须晚于开始时间"""
        start = attrs.get("start_time") or getattr(self.instance, "start_time", None)
        end = attrs.get("end_time") or getattr(self.instance, "end_time", None)
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_time": "结束时间必须晚于开始时间"}
            )
        return attrs


class AlertHistorySerializer(serializers.ModelSerializer):
    """告警历史（只读为主，支持确认/解决操作）"""

    level_display = serializers.CharField(source="get_level_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    rule_name = serializers.CharField(source="rule.name", read_only=True, default="")
    acknowledged_by_name = serializers.CharField(
        source="acknowledged_by.username", read_only=True, default=""
    )
    resolved_by_name = serializers.CharField(
        source="resolved_by.username", read_only=True, default=""
    )

    class Meta:
        model = AlertHistory
        fields = [
            "id",
            "rule",
            "rule_name",
            "level",
            "level_display",
            "title",
            "content",
            "status",
            "status_display",
            "channels",
            "sent_channels",
            "error_message",
            "occurrences",
            "first_occurred_at",
            "last_occurred_at",
            "acknowledged",
            "acknowledged_at",
            "acknowledged_by",
            "acknowledged_by_name",
            "resolved",
            "resolved_at",
            "resolved_by",
            "resolved_by_name",
            "context",
        ]
        read_only_fields = [
            "id",
            "status",
            "sent_channels",
            "error_message",
            "occurrences",
            "first_occurred_at",
            "last_occurred_at",
            "acknowledged",
            "acknowledged_at",
            "acknowledged_by",
            "resolved",
            "resolved_at",
            "resolved_by",
        ]


class AlertNotificationConfigSerializer(serializers.ModelSerializer):
    """通知渠道配置"""

    channel_display = serializers.CharField(
        source="get_channel_display", read_only=True
    )
    # 凭据写入专用：API 读取不返回明文（脱敏），避免 webhook/token/secret 泄漏
    config = serializers.JSONField(
        write_only=True,
        help_text="渠道配置（webhook/token/secret 等），写入后不通过 API 明文返回",
    )
    config_masked = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AlertNotificationConfig
        fields = [
            "id",
            "name",
            "channel",
            "channel_display",
            "config",
            "config_masked",
            "enabled",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_config_masked(self, obj):
        if not obj.config:
            return None
        return {"_masked": True, "configured": True}

    def validate(self, attrs):
        """is_default 唯一性 — 每个渠道只能有一个默认配置"""
        is_default = attrs.get("is_default", False)
        channel = attrs.get("channel") or getattr(self.instance, "channel", None)
        if is_default and channel:
            qs = AlertNotificationConfig.objects.filter(
                channel=channel, is_default=True
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"is_default": f"渠道 '{channel}' 已有默认配置"}
                )
        return attrs


# ---------------------------------------------------------------
# Action Serializers（用于自定义 @action）
# ---------------------------------------------------------------

class AcknowledgeActionSerializer(serializers.Serializer):
    """确认告警"""

    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class ResolveActionSerializer(serializers.Serializer):
    """解决告警"""

    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TriggerAlertSerializer(serializers.Serializer):
    """手动触发告警（测试用）"""

    rule_id = serializers.IntegerField(required=False)
    level = serializers.ChoiceField(choices=AlertLevel.choices, default=AlertLevel.WARNING)
    title = serializers.CharField(max_length=500)
    content = serializers.CharField()
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=AlertChannel.choices),
        required=False,
        default=list,
    )
    context = serializers.JSONField(required=False, default=dict)


class TestNotifySerializer(serializers.Serializer):
    """测试通知渠道"""

    channel = serializers.ChoiceField(choices=AlertChannel.choices)
    title = serializers.CharField(max_length=200, default="测试通知")
    content = serializers.CharField(default="这是一条来自告警系统的测试消息")
