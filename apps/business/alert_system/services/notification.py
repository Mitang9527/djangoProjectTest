"""
通知渠道分发器 — 统一抽象层

把 framework/notice_utils/ 下的 4 个独立渠道控制器（钉钉/飞书/邮件/企微）
收编为插件式渠道，供 alert_engine 调用。

设计要点:
- 每个渠道一个 _send_xxx 方法，返回 (success: bool, error: str | None)
- 配置来源: AlertNotificationConfig.config (JSON) > settings 全局配置
- 失败不抛异常，返回错误信息由调用方记录
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from ..models import AlertChannel, AlertNotificationConfig

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """统一通知分发器"""

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    @classmethod
    def dispatch(
        cls,
        channels: list[str],
        title: str,
        content: str,
        level: str = "warning",
        context: dict | None = None,
    ) -> dict[str, Any]:
        """
        向多个渠道发送通知。

        Args:
            channels: 渠道列表 ['email', 'dingtalk', 'feishu']
            title: 通知标题
            content: 通知内容（纯文本）
            level: 告警级别 info/warning/error/critical
            context: 附加上下文（可含 request_id 等）

        Returns:
            {
                'email': {'success': True, 'error': None},
                'dingtalk': {'success': False, 'error': 'webhook not configured'},
                ...
            }
        """
        results: dict[str, Any] = {}
        for channel in channels:
            handler = cls._get_handler(channel)
            if handler is None:
                results[channel] = {
                    "success": False,
                    "error": f"不支持的渠道: {channel}",
                }
                continue
            try:
                success, error = handler(title, content, level, context or {})
                results[channel] = {"success": success, "error": error}
            except Exception as exc:
                logger.exception("通知渠道 %s 发送异常", channel)
                results[channel] = {"success": False, "error": str(exc)}
        return results

    # ------------------------------------------------------------------
    # 渠道路由
    # ------------------------------------------------------------------

    @classmethod
    def _get_handler(cls, channel: str):
        """根据渠道名返回对应的发送函数"""
        mapping = {
            AlertChannel.EMAIL: cls._send_email,
            AlertChannel.DINGTALK: cls._send_dingtalk,
            AlertChannel.FEISHU: cls._send_feishu,
        }
        return mapping.get(channel)

    # ------------------------------------------------------------------
    # 配置获取
    # ------------------------------------------------------------------

    @classmethod
    def _get_config(cls, channel: str) -> dict:
        """
        获取渠道配置: 优先 AlertNotificationConfig，兜底 settings 全局配置。
        """
        # 1. 查数据库配置（default 优先）
        db_config = (
            AlertNotificationConfig.objects.filter(
                channel=channel, enabled=True, is_default=True
            )
            .first()
        )
        if db_config:
            return db_config.config or {}

        # 2. 兜底 settings 全局配置
        return cls._get_settings_config(channel)

    @staticmethod
    def _get_settings_config(channel: str) -> dict:
        """从 settings 获取各渠道的全局配置"""
        if channel == AlertChannel.EMAIL:
            return {
                "recipients": getattr(settings, "EMAIL_SEND_LIST", "").split(","),
                "sender": getattr(settings, "EMAIL_SEND_USER", ""),
            }
        elif channel == AlertChannel.DINGTALK:
            return {
                "webhook": getattr(settings, "DINGTALK_WEBHOOK", ""),
                "secret": getattr(settings, "DINGTALK_SECRET", ""),
            }
        elif channel == AlertChannel.FEISHU:
            return {
                "webhook": getattr(settings, "FEISHU_WEBHOOK", ""),
                "secret": getattr(settings, "FEISHU_SECRET", ""),
            }
        return {}

    # ------------------------------------------------------------------
    # 各渠道实现
    # ------------------------------------------------------------------

    @classmethod
    def _send_email(
        cls, title: str, content: str, level: str, context: dict
    ) -> tuple[bool, str | None]:
        """发送邮件"""
        config = cls._get_config(AlertChannel.EMAIL)
        recipients = config.get("recipients", [])
        if not recipients or not recipients[0]:
            return False, "邮件收件人未配置 (EMAIL_SEND_LIST)"

        try:
            from framework.notice_utils.sendmail_control import SendEmail

            full_content = cls._format_content(title, content, level, context)
            SendEmail.send_mail(recipients, f"[{level.upper()}] {title}", full_content)
            return True, None
        except Exception as exc:
            return False, str(exc)

    @classmethod
    def _send_dingtalk(
        cls, title: str, content: str, level: str, context: dict
    ) -> tuple[bool, str | None]:
        """发送钉钉通知"""
        config = cls._get_config(AlertChannel.DINGTALK)
        webhook = config.get("webhook", "")
        if not webhook:
            return False, "钉钉 webhook 未配置 (DINGTALK_WEBHOOK)"

        try:
            from framework.notice_utils.dingtalk_control import DingTalkSendMsg

            msg = cls._format_markdown(title, content, level, context)
            sender = DingTalkSendMsg()
            sender.send_markdown(title=f"[{level.upper()}] {title}", msg=msg)
            return True, None
        except Exception as exc:
            return False, str(exc)

    @classmethod
    def _send_feishu(
        cls, title: str, content: str, level: str, context: dict
    ) -> tuple[bool, str | None]:
        """发送飞书通知"""
        config = cls._get_config(AlertChannel.FEISHU)
        webhook = config.get("webhook", "")
        if not webhook:
            return False, "飞书 webhook 未配置 (FEISHU_WEBHOOK)"

        try:
            from framework.notice_utils.feishu_control import FeiShuTalkChatBot

            msg = cls._format_content(title, content, level, context)
            bot = FeiShuTalkChatBot()
            bot.send_text(msg)
            return True, None
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------

    @staticmethod
    def _format_content(
        title: str, content: str, level: str, context: dict
    ) -> str:
        """格式化纯文本内容"""
        lines = [
            f"告警标题: {title}",
            f"告警级别: {level.upper()}",
            f"告警内容: {content}",
        ]
        if context:
            lines.append(f"上下文: {json.dumps(context, ensure_ascii=False, default=str)}")
        return "\n".join(lines)

    @staticmethod
    def _format_markdown(
        title: str, content: str, level: str, context: dict
    ) -> str:
        """格式化 Markdown 内容（钉钉/飞书用）"""
        level_emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }
        emoji = level_emoji.get(level, "⚠️")
        lines = [
            f"#### {emoji} {title}",
            f"",
            f"> **级别**: {level.upper()}",
            f"> **时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"**内容**:",
            f"```",
            content,
            f"```",
        ]
        if context:
            lines.append(f"\n**上下文**:")
            for k, v in context.items():
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)
