"""
告警引擎 — 核心业务逻辑

职责:
1. 规则匹配 — 根据 condition_type (log_level / keyword / custom) 匹配告警规则
2. 静默检查 — 检查 AlertSilence 是否命中
3. 抑制窗口 — 相同告警在 suppression_window 分钟内只记录不发送
4. 通知分发 — 调用 NotificationDispatcher 向渠道发送
5. 确认/解决 — AlertHistory 状态流转
6. 升级检查 — 超时未确认的告警自动升级

调用方式:
    from business.alert_system.services.alert_engine import AlertEngine

    # 1. 评估日志（从日志中间件调用）
    AlertEngine.evaluate(log_level='ERROR', message='DB connection failed', context={...})

    # 2. 手动触发告警
    AlertEngine.trigger(rule=rule_obj, title='手动告警', content='...')

    # 3. 确认/解决
    AlertEngine.acknowledge(history_id=1, user=request.user)
    AlertEngine.resolve(history_id=1, user=request.user)
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from loguru import logger

from ..models import (
    AlertRule,
    AlertSilence,
    AlertHistory,
    AlertLevel,
    AlertStatus,
)
from .notification import NotificationDispatcher


# 日志级别数值映射（用于 log_level 条件比较）
_LEVEL_PRIORITY = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}


class AlertEngine:
    """告警引擎"""

    # ==================================================
    # 1. 规则匹配
    # ==================================================

    @classmethod
    def evaluate(
        cls,
        log_level: str | None = None,
        message: str = "",
        context: dict | None = None,
    ) -> list[AlertHistory]:
        """
        评估日志/事件，匹配启用的告警规则并触发告警。

        Args:
            log_level: 日志级别 (debug/info/warning/error/critical)
            message: 日志消息
            context: 附加上下文

        Returns:
            本次触发的 AlertHistory 列表（可能为空、可能被抑制/静默）
        """
        triggered: list[AlertHistory] = []
        context = context or {}

        # 只检查启用的规则
        rules = AlertRule.objects.filter(enabled=True)
        if not rules.exists():
            return triggered

        for rule in rules:
            if not cls._match_rule(rule, log_level, message):
                continue

            # 命中规则，构建标题和内容
            title = cls._build_title(rule, message)
            content = cls._build_content(rule, message, context)

            # 静默检查
            if cls._check_silence(rule, title, content):
                history = cls._record_silenced(rule, title, content, context)
                triggered.append(history)
                logger.debug("告警被静默: rule=%s title=%s", rule.name, title)
                continue

            # 抑制窗口检查
            should_send, history = cls._check_suppression(rule, title, content, context)
            triggered.append(history)

            if should_send:
                # 异步发送通知
                cls._dispatch_async(history)

        return triggered

    # ==================================================
    # 2. 手动触发
    # ==================================================

    @classmethod
    def trigger(
        cls,
        title: str,
        content: str,
        rule: AlertRule | None = None,
        level: str = AlertLevel.WARNING,
        channels: list[str] | None = None,
        context: dict | None = None,
    ) -> AlertHistory:
        """
        手动触发一条告警（不走规则匹配流程）。

        Args:
            title: 告警标题
            content: 告警内容
            rule: 关联规则（可选）
            level: 告警级别
            channels: 通知渠道（为空时取 rule.channels 或默认配置）
            context: 上下文
        """
        context = context or {}

        # 指标：记录告警触发（供 Prometheus 采集）
        try:
            from framework.metrics.metrics import ALERTS_TRIGGERED_TOTAL

            ALERTS_TRIGGERED_TOTAL.labels(level=level).inc()
        except Exception:  # pragma: no cover - 埋点不应影响主流程
            pass

        if channels is None:
            channels = rule.channels if rule else []

        with transaction.atomic():
            history = AlertHistory.objects.create(
                rule=rule,
                level=level,
                title=title,
                content=content,
                status=AlertStatus.PENDING,
                channels=channels,
                context=context,
            )

        # 发送通知
        if channels:
            cls._dispatch_async(history)
        else:
            logger.warning("告警 %s 无通知渠道，跳过发送", history.pk)

        return history

    # ==================================================
    # 3. 确认 / 解决
    # ==================================================

    @classmethod
    def acknowledge(cls, history_id: int, user) -> AlertHistory | None:
        """确认告警"""
        try:
            history = AlertHistory.objects.get(pk=history_id)
        except AlertHistory.DoesNotExist:
            return None

        if history.acknowledged:
            return history

        history.acknowledged = True
        history.acknowledged_at = timezone.now()
        history.acknowledged_by = user
        history.save(update_fields=[
            "acknowledged", "acknowledged_at", "acknowledged_by",
        ])
        logger.info("告警 %s 已被 %s 确认", history_id, user.username)
        return history

    @classmethod
    def resolve(cls, history_id: int, user) -> AlertHistory | None:
        """解决告警"""
        try:
            history = AlertHistory.objects.get(pk=history_id)
        except AlertHistory.DoesNotExist:
            return None

        if history.resolved:
            return history

        history.resolved = True
        history.resolved_at = timezone.now()
        history.resolved_by = user
        # 解决时自动确认（如果尚未确认）
        if not history.acknowledged:
            history.acknowledged = True
            history.acknowledged_at = timezone.now()
            history.acknowledged_by = user
        history.save(update_fields=[
            "resolved", "resolved_at", "resolved_by",
            "acknowledged", "acknowledged_at", "acknowledged_by",
        ])
        logger.info("告警 %s 已被 %s 解决", history_id, user.username)
        return history

    # ==================================================
    # 4. 升级检查（定时任务调用）
    # ==================================================

    @classmethod
    def check_escalations(cls) -> int:
        """
        检查需要升级的告警。
        遍历已确认但未解决 + 超过 escalation_rules.delay_minutes 的告警，
        自动提升级别并重新发送通知。

        Returns:
            本次升级的告警数量
        """
        now = timezone.now()
        escalated_count = 0

        # 只检查有升级规则、未解决的告警
        pending = AlertHistory.objects.filter(
            resolved=False,
            rule__isnull=False,
        ).select_related("rule")

        for history in pending:
            if not history.rule or not history.rule.escalation_rules:
                continue

            for escalation in history.rule.escalation_rules:
                delay_minutes = escalation.get("delay_minutes", 0)
                target_level = escalation.get("level", "")

                # 检查是否已超过升级时间
                escalate_at = history.first_occurred_at + timedelta(minutes=delay_minutes)
                if now < escalate_at:
                    continue

                # 检查是否已升级到该级别
                if history.context.get("_escalated_to", "") == target_level:
                    continue

                # 执行升级
                old_level = history.level
                if target_level and target_level in dict(AlertLevel.choices):
                    history.level = target_level

                escalation_channels = escalation.get("channels", history.channels)
                history.channels = list(set(history.channels + escalation_channels))

                # 标记已升级
                ctx = dict(history.context) if history.context else {}
                ctx["_escalated_to"] = target_level
                ctx["_escalated_at"] = now.isoformat()
                ctx["_escalated_from"] = old_level
                history.context = ctx

                history.save(update_fields=["level", "channels", "context"])
                escalated_count += 1

                # 重新发送通知
                cls._dispatch_async(history)

                logger.warning(
                    "告警 %s 升级: %s → %s",
                    history.pk, old_level, target_level,
                )

        return escalated_count

    # ==================================================
    # 5. 统计
    # ==================================================

    @classmethod
    def get_stats(cls) -> dict[str, Any]:
        """获取告警统计"""
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_7d = today_start - timedelta(days=7)

        qs = AlertHistory.objects.all()
        today_qs = qs.filter(first_occurred_at__gte=today_start)
        week_qs = qs.filter(first_occurred_at__gte=last_7d)

        return {
            "total": qs.count(),
            "today": today_qs.count(),
            "week": week_qs.count(),
            "pending": qs.filter(resolved=False).count(),
            "acknowledged": qs.filter(acknowledged=True, resolved=False).count(),
            "resolved": qs.filter(resolved=True).count(),
            "by_level": {
                level: qs.filter(level=level).count()
                for level, _ in AlertLevel.choices
            },
            "by_status": {
                status: qs.filter(status=status).count()
                for status, _ in AlertStatus.choices
            },
            "active_rules": AlertRule.objects.filter(enabled=True).count(),
            "active_silences": AlertSilence.objects.filter(enabled=True).count(),
        }

    # ==================================================
    # 内部方法
    # ==================================================

    @staticmethod
    def _match_rule(rule: AlertRule, log_level: str | None, message: str) -> bool:
        """检查日志是否匹配规则条件"""
        if rule.condition_type == "log_level":
            # 日志级别匹配: condition_value 为阈值级别，>= 即触发
            threshold = _LEVEL_PRIORITY.get(rule.condition_value.lower(), 0)
            actual = _LEVEL_PRIORITY.get((log_level or "").lower(), 0)
            return actual >= threshold > 0

        elif rule.condition_type == "keyword":
            # 关键词匹配: condition_value 为逗号分隔的关键词列表
            keywords = [kw.strip() for kw in rule.condition_value.split(",") if kw.strip()]
            return any(kw in message for kw in keywords)

        elif rule.condition_type == "custom":
            # 自定义条件: condition_value 为正则表达式
            try:
                return bool(re.search(rule.condition_value, message))
            except re.error:
                logger.error("规则 %s 的正则表达式无效: %s", rule.pk, rule.condition_value)
                return False

        return False

    @staticmethod
    def _build_title(rule: AlertRule, message: str) -> str:
        """构建告警标题"""
        # 截取消息前 80 字符作为标题
        msg_preview = message[:80] + ("..." if len(message) > 80 else "")
        return f"[{rule.name}] {msg_preview}"

    @staticmethod
    def _build_content(rule: AlertRule, message: str, context: dict) -> str:
        """构建告警内容"""
        import json
        lines = [
            f"规则: {rule.name}",
            f"级别: {rule.level}",
            f"条件: {rule.condition_type} = {rule.condition_value}",
            f"",
            f"消息:",
            message,
        ]
        if context:
            lines.append(f"\n上下文: {json.dumps(context, ensure_ascii=False, default=str)}")
        return "\n".join(lines)

    @classmethod
    def _check_silence(
        cls, rule: AlertRule, title: str, content: str
    ) -> bool:
        """检查是否被静默"""
        now = timezone.now()
        # 检查关联此规则的静默配置 + 全局静默配置
        silences = AlertSilence.objects.filter(enabled=True, start_time__lte=now, end_time__gte=now)
        for silence in silences:
            # 如果静默配置关联了特定规则，只匹配该规则
            if silence.rule_id and silence.rule_id != rule.pk:
                continue
            # 如果有匹配模式，检查标题和内容
            if silence.match_pattern:
                try:
                    if re.search(silence.match_pattern, f"{title}\n{content}"):
                        return True
                except re.error:
                    pass
            else:
                # 无匹配模式 = 匹配所有（如果关联了此规则）
                if silence.rule_id == rule.pk:
                    return True
        return False

    @classmethod
    def _check_suppression(
        cls,
        rule: AlertRule,
        title: str,
        content: str,
        context: dict,
    ) -> tuple[bool, AlertHistory]:
        """
        检查抑制窗口。

        Returns:
            (should_send, history)
            - should_send=True: 新告警或超过窗口，需要发送
            - should_send=False: 被抑制（只更新 occurrences）
        """
        now = timezone.now()
        window_start = now - timedelta(minutes=rule.suppression_window)

        # 查找窗口内相同规则+相同标题的告警
        existing = (
            AlertHistory.objects.filter(
                rule=rule,
                title=title,
                last_occurred_at__gte=window_start,
            )
            .order_by("-last_occurred_at")
            .first()
        )

        if existing:
            # 命中抑制 — 更新次数
            existing.occurrences += 1
            existing.last_occurred_at = now
            # 检查是否超过最大触发次数
            if existing.occurrences > rule.max_occurrences:
                existing.status = AlertStatus.SUPPRESSED
            else:
                existing.status = AlertStatus.SUPPRESSED
            existing.save(update_fields=[
                "occurrences", "last_occurred_at", "status",
            ])
            return False, existing

        # 新告警 — 创建记录
        history = AlertHistory.objects.create(
            rule=rule,
            level=rule.level,
            title=title,
            content=content,
            status=AlertStatus.PENDING,
            channels=rule.channels,
            context=context,
        )
        return True, history

    @classmethod
    def _record_silenced(
        cls,
        rule: AlertRule,
        title: str,
        content: str,
        context: dict,
    ) -> AlertHistory:
        """记录被静默的告警"""
        return AlertHistory.objects.create(
            rule=rule,
            level=rule.level,
            title=title,
            content=content,
            status=AlertStatus.SILENCED,
            channels=rule.channels,
            context=context,
        )

    @classmethod
    def _dispatch_async(cls, history: AlertHistory) -> None:
        """
        异步发送通知。
        优先使用 Celery，未配置时降级为同步发送。
        """
        try:
            from ..tasks import dispatch_alert

            dispatch_alert.delay(history.pk)
        except Exception:
            # Celery 不可用 — 同步发送
            cls._dispatch_sync(history)

    @classmethod
    def _dispatch_sync(cls, history: AlertHistory) -> None:
        """同步发送通知"""
        results = NotificationDispatcher.dispatch(
            channels=history.channels,
            title=history.title,
            content=history.content,
            level=history.level,
            context=history.context,
        )

        sent_channels = []
        errors = []
        for channel, result in results.items():
            if result["success"]:
                sent_channels.append(channel)
            else:
                errors.append(f"{channel}: {result['error']}")

        if errors and not sent_channels:
            history.status = AlertStatus.FAILED
            history.error_message = "; ".join(errors)
        elif errors and sent_channels:
            history.status = AlertStatus.SENT
            history.error_message = "; ".join(errors)
        else:
            history.status = AlertStatus.SENT

        history.sent_channels = sent_channels
        history.save(update_fields=[
            "status", "sent_channels", "error_message",
        ])
