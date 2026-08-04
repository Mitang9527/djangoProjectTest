"""
告警系统测试 — 核心业务逻辑

覆盖:
- AlertEngine 规则匹配 (log_level / keyword / custom)
- AlertEngine 静默检查
- AlertEngine 抑制窗口
- AlertEngine 确认/解决
- AlertEngine 升级检查
- AlertEngine 统计
- NotificationDispatcher 配置获取
- Serializer 校验
"""

import json
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest
from django.utils import timezone

from business.alert_system.models import (
    AlertRule,
    AlertSilence,
    AlertHistory,
    AlertNotificationConfig,
    AlertLevel,
    AlertStatus,
    AlertChannel,
)
from business.alert_system.services import AlertEngine, NotificationDispatcher
from business.alert_system.serializers import (
    AlertRuleSerializer,
    TriggerAlertSerializer,
    TestNotifySerializer,
    AlertNotificationConfigSerializer,
)


# ==================================================
# Fixtures
# ==================================================

@pytest.fixture
def alert_rule(db):
    """创建一条告警规则"""
    return AlertRule.objects.create(
        name="ERROR 日志告警",
        description="匹配所有 ERROR 级别日志",
        enabled=True,
        level=AlertLevel.ERROR,
        condition_type="log_level",
        condition_value="error",
        channels=["dingtalk", "feishu"],
        suppression_window=5,
        max_occurrences=10,
    )


@pytest.fixture
def keyword_rule(db):
    """关键词匹配规则"""
    return AlertRule.objects.create(
        name="数据库异常告警",
        enabled=True,
        level=AlertLevel.CRITICAL,
        condition_type="keyword",
        condition_value="数据库,连接失败,timeout",
        channels=["email"],
        suppression_window=1,
        max_occurrences=3,
    )


@pytest.fixture
def custom_rule(db):
    """自定义正则匹配规则"""
    return AlertRule.objects.create(
        name="HTTP 5xx 告警",
        enabled=True,
        level=AlertLevel.WARNING,
        condition_type="custom",
        condition_value=r"HTTP \d{3}",
        channels=["dingtalk"],
        suppression_window=60,
        max_occurrences=100,
    )


# ==================================================
# 规则匹配测试
# ==================================================

@pytest.mark.django_db
class TestAlertEngineMatch:
    """AlertEngine._match_rule 测试"""

    def test_log_level_match(self, alert_rule):
        """日志级别 >= 阈值时匹配"""
        assert AlertEngine._match_rule(alert_rule, "error", "something went wrong") is True
        assert AlertEngine._match_rule(alert_rule, "critical", "fatal error") is True
        assert AlertEngine._match_rule(alert_rule, "info", "just info") is False
        assert AlertEngine._match_rule(alert_rule, "warning", "warning msg") is False

    def test_keyword_match(self, keyword_rule):
        """关键词命中时匹配"""
        assert AlertEngine._match_rule(keyword_rule, None, "数据库连接失败") is True
        assert AlertEngine._match_rule(keyword_rule, None, "连接超时 timeout") is True
        assert AlertEngine._match_rule(keyword_rule, None, "一切正常") is False

    def test_custom_regex_match(self, custom_rule):
        """正则匹配"""
        assert AlertEngine._match_rule(custom_rule, None, "HTTP 500 Internal Server Error") is True
        assert AlertEngine._match_rule(custom_rule, None, "HTTP 404 Not Found") is True
        assert AlertEngine._match_rule(custom_rule, None, "no match here") is False

    def test_invalid_regex(self, db):
        """无效正则不匹配，不抛异常"""
        rule = AlertRule.objects.create(
            name="bad regex",
            enabled=True,
            condition_type="custom",
            condition_value="[invalid(",
            channels=[],
        )
        assert AlertEngine._match_rule(rule, None, "test") is False


# ==================================================
# 抑制窗口测试
# ==================================================

@pytest.mark.django_db
class TestSuppressionWindow:
    """AlertEngine._check_suppression 测试"""

    def test_first_alert_creates_history(self, alert_rule):
        """首次告警创建新记录，should_send=True"""
        should_send, history = AlertEngine._check_suppression(
            alert_rule, "[ERROR 日志告警] test", "content", {}
        )
        assert should_send is True
        assert history.pk is not None
        assert history.status == AlertStatus.PENDING
        assert history.occurrences == 1

    def test_second_alert_within_window_suppressed(self, alert_rule):
        """窗口内重复告警被抑制"""
        # 第一次
        AlertEngine._check_suppression(alert_rule, "title", "content", {})
        # 第二次（窗口内）
        should_send, history = AlertEngine._check_suppression(
            alert_rule, "title", "content", {}
        )
        assert should_send is False
        assert history.occurrences == 2
        assert history.status == AlertStatus.SUPPRESSED

    def test_alert_after_window_not_suppressed(self, alert_rule):
        """窗口过期后的告警创建新记录"""
        # 第一次
        _, first = AlertEngine._check_suppression(alert_rule, "title", "content", {})
        # 模拟窗口过期
        first.last_occurred_at = timezone.now() - timedelta(minutes=10)
        first.save(update_fields=["last_occurred_at"])
        # 第二次（窗口外）
        should_send, second = AlertEngine._check_suppression(
            alert_rule, "title", "content", {}
        )
        assert should_send is True
        assert second.pk != first.pk


# ==================================================
# 静默检查测试
# ==================================================

@pytest.mark.django_db
class TestSilenceCheck:
    """AlertEngine._check_silence 测试"""

    def test_silence_active_matches_rule(self, alert_rule):
        """活跃静默配置匹配时返回 True"""
        AlertSilence.objects.create(
            name="夜间静默",
            rule=alert_rule,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            enabled=True,
        )
        assert AlertEngine._check_silence(alert_rule, "title", "content") is True

    def test_silence_expired_not_matched(self, alert_rule):
        """过期静默配置不匹配"""
        AlertSilence.objects.create(
            name="过期静默",
            rule=alert_rule,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            enabled=True,
        )
        assert AlertEngine._check_silence(alert_rule, "title", "content") is False

    def test_silence_pattern_match(self, alert_rule):
        """正则匹配模式"""
        AlertSilence.objects.create(
            name="特定内容静默",
            rule=alert_rule,
            match_pattern=r"healthcheck",
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            enabled=True,
        )
        assert AlertEngine._check_silence(alert_rule, "healthcheck", "content") is True
        assert AlertEngine._check_silence(alert_rule, "real error", "content") is False

    def test_silence_disabled_not_matched(self, alert_rule):
        """禁用的静默配置不匹配"""
        AlertSilence.objects.create(
            name="禁用静默",
            rule=alert_rule,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=1),
            enabled=False,
        )
        assert AlertEngine._check_silence(alert_rule, "title", "content") is False


# ==================================================
# 确认/解决测试
# ==================================================

@pytest.mark.django_db
class TestAcknowledgeResolve:
    """AlertEngine.acknowledge / resolve 测试"""

    def test_acknowledge(self, alert_rule, django_user_model):
        user = django_user_model.objects.create_user(username="testuser", password="pass")
        history = AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.ERROR,
            title="test",
            content="content",
        )
        result = AlertEngine.acknowledge(history.pk, user)
        assert result.acknowledged is True
        assert result.acknowledged_by == user
        assert result.acknowledged_at is not None

    def test_acknowledge_already_acknowledged(self, alert_rule, django_user_model):
        user = django_user_model.objects.create_user(username="testuser2", password="pass")
        history = AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.ERROR,
            title="test",
            content="content",
            acknowledged=True,
            acknowledged_at=timezone.now(),
            acknowledged_by=user,
        )
        result = AlertEngine.acknowledge(history.pk, user)
        assert result.acknowledged is True
        # 不重复设置
        assert result.acknowledged_at == history.acknowledged_at

    def test_resolve(self, alert_rule, django_user_model):
        user = django_user_model.objects.create_user(username="resolver", password="pass")
        history = AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.ERROR,
            title="test",
            content="content",
        )
        result = AlertEngine.resolve(history.pk, user)
        assert result.resolved is True
        assert result.resolved_by == user
        # 解决时自动确认
        assert result.acknowledged is True

    def test_acknowledge_nonexistent(self):
        result = AlertEngine.acknowledge(99999, None)
        assert result is None

    def test_resolve_nonexistent(self):
        result = AlertEngine.resolve(99999, None)
        assert result is None


# ==================================================
# 升级检查测试
# ==================================================

@pytest.mark.django_db
class TestEscalation:
    """AlertEngine.check_escalations 测试"""

    def test_escalation_triggers(self, alert_rule, django_user_model):
        """超过升级时间后自动升级"""
        # 给规则添加升级规则
        alert_rule.escalation_rules = [
            {"delay_minutes": 5, "level": "critical", "channels": ["email"]}
        ]
        alert_rule.save()

        # 创建一条已过期的告警（5分钟前触发）
        history = AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.ERROR,
            title="escalation test",
            content="content",
            first_occurred_at=timezone.now() - timedelta(minutes=10),
            last_occurred_at=timezone.now() - timedelta(minutes=10),
        )

        count = AlertEngine.check_escalations()
        assert count == 1

        history.refresh_from_db()
        assert history.level == "critical"
        assert "email" in history.channels
        assert history.context.get("_escalated_to") == "critical"

    def test_no_escalation_within_delay(self, alert_rule):
        """未超过升级时间不升级"""
        alert_rule.escalation_rules = [
            {"delay_minutes": 60, "level": "critical", "channels": ["email"]}
        ]
        alert_rule.save()

        AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.ERROR,
            title="recent alert",
            content="content",
        )

        count = AlertEngine.check_escalations()
        assert count == 0


# ==================================================
# 统计测试
# ==================================================

@pytest.mark.django_db
class TestStats:
    """AlertEngine.get_stats 测试"""

    def test_empty_stats(self):
        stats = AlertEngine.get_stats()
        assert stats["total"] == 0
        assert stats["today"] == 0
        assert stats["pending"] == 0
        assert stats["active_rules"] == 0

    def test_stats_with_data(self, alert_rule):
        AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.ERROR,
            title="alert 1",
            content="content",
        )
        AlertHistory.objects.create(
            rule=alert_rule,
            level=AlertLevel.WARNING,
            title="alert 2",
            content="content",
            resolved=True,
        )

        stats = AlertEngine.get_stats()
        assert stats["total"] == 2
        assert stats["pending"] == 1
        assert stats["resolved"] == 1
        assert stats["active_rules"] == 1
        assert stats["by_level"]["error"] == 1
        assert stats["by_level"]["warning"] == 1


# ==================================================
# 手动触发测试
# ==================================================

@pytest.mark.django_db
class TestTrigger:
    """AlertEngine.trigger 测试"""

    def test_trigger_creates_history(self, alert_rule):
        history = AlertEngine.trigger(
            title="手动告警",
            content="这是手动触发的告警",
            rule=alert_rule,
            level=AlertLevel.CRITICAL,
            channels=["dingtalk"],
            context={"source": "manual"},
        )
        assert history.pk is not None
        assert history.title == "手动告警"
        assert history.level == AlertLevel.CRITICAL
        assert history.channels == ["dingtalk"]
        assert history.context == {"source": "manual"}

    def test_trigger_without_rule(self):
        history = AlertEngine.trigger(
            title="无规则告警",
            content="content",
            level=AlertLevel.INFO,
        )
        assert history.pk is not None
        assert history.rule is None
        assert history.channels == []


# ==================================================
# Serializer 测试
# ==================================================

@pytest.mark.django_db
class TestSerializers:
    """序列化器校验测试"""

    def test_rule_serializer_valid_channels(self):
        data = {
            "name": "test rule",
            "level": "warning",
            "condition_type": "keyword",
            "condition_value": "error",
            "channels": ["email", "dingtalk"],
        }
        serializer = AlertRuleSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_rule_serializer_invalid_channel(self):
        data = {
            "name": "test rule",
            "condition_type": "keyword",
            "condition_value": "error",
            "channels": ["invalid_channel"],
        }
        serializer = AlertRuleSerializer(data=data)
        assert not serializer.is_valid()
        assert "channels" in serializer.errors

    def test_trigger_serializer_valid(self):
        data = {
            "level": "error",
            "title": "test alert",
            "content": "test content",
            "channels": ["email"],
        }
        serializer = TriggerAlertSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_notification_config_default_uniqueness(self):
        """同一渠道只能有一个默认配置"""
        AlertNotificationConfig.objects.create(
            name="default email",
            channel=AlertChannel.EMAIL,
            config={},
            is_default=True,
        )
        serializer = AlertNotificationConfigSerializer(
            data={"name": "another", "channel": "email", "config": {}, "is_default": True}
        )
        assert not serializer.is_valid()
        assert "is_default" in serializer.errors


# ==================================================
# NotificationDispatcher 测试
# ==================================================

@pytest.mark.django_db
class TestNotificationDispatcher:
    """通知分发器测试"""

    def test_dispatch_unsupported_channel(self):
        results = NotificationDispatcher.dispatch(
            channels=["unknown"],
            title="test",
            content="content",
        )
        assert results["unknown"]["success"] is False

    @patch("business.alert_system.services.notification.NotificationDispatcher._send_dingtalk")
    def test_dispatch_dingtalk_success(self, mock_send):
        mock_send.return_value = (True, None)
        results = NotificationDispatcher.dispatch(
            channels=["dingtalk"],
            title="test",
            content="content",
            level="warning",
        )
        assert results["dingtalk"]["success"] is True

    def test_get_config_from_db(self):
        """数据库配置优先"""
        AlertNotificationConfig.objects.create(
            name="test config",
            channel=AlertChannel.DINGTALK,
            config={"webhook": "https://test.com/webhook"},
            is_default=True,
            enabled=True,
        )
        config = NotificationDispatcher._get_config(AlertChannel.DINGTALK)
        assert config["webhook"] == "https://test.com/webhook"

    def test_get_config_fallback_to_settings(self):
        """无数据库配置时兜底 settings"""
        config = NotificationDispatcher._get_config(AlertChannel.EMAIL)
        # 应该从 settings 获取
        assert "recipients" in config or "sender" in config
