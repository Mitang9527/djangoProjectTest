"""
通知渠道分发器（独立服务版，不依赖 alert_system）。

- 支持渠道: email / dingtalk / feishu / wechat
- 渠道配置统一来自 Django settings（即环境变量）；本版不读取 alert_system 的
  AlertNotificationConfig 数据库配置，保持无状态。
- 失败不抛异常，返回 (success, error) 由调用方记录。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

CHANNEL_EMAIL = "email"
CHANNEL_DINGTALK = "dingtalk"
CHANNEL_FEISHU = "feishu"
CHANNEL_WECHAT = "wechat"
SUPPORTED = {CHANNEL_EMAIL, CHANNEL_DINGTALK, CHANNEL_FEISHU, CHANNEL_WECHAT}


class NotificationDispatcher:
    """统一通知分发器（无状态服务版）。"""

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    @classmethod
    def dispatch(
        cls,
        *,
        channels: list[str],
        title: str,
        content: str,
        level: str = "warning",
        context: dict | None = None,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for channel in channels:
            if channel not in SUPPORTED:
                results[channel] = {"success": False, "error": f"不支持的渠道: {channel}"}
                continue
            try:
                success, error = cls._send(channel, title, content, level, context or {})
                results[channel] = {"success": success, "error": error}
            except Exception as exc:
                logger.exception("通知渠道 %s 发送异常", channel)
                results[channel] = {"success": False, "error": str(exc)}
        return results

    # ------------------------------------------------------------------
    # 渠道路由
    # ------------------------------------------------------------------
    @classmethod
    def _send(cls, channel, title, content, level, context) -> tuple[bool, str | None]:
        if channel == CHANNEL_EMAIL:
            return cls._send_email(title, content, level, context)
        if channel == CHANNEL_DINGTALK:
            return cls._send_dingtalk(title, content, level, context)
        if channel == CHANNEL_FEISHU:
            return cls._send_feishu(title, content, level, context)
        if channel == CHANNEL_WECHAT:
            return cls._send_wechat(title, content, level, context)
        return False, f"未实现渠道: {channel}"

    # ------------------------------------------------------------------
    # 配置读取（来自 settings / 环境变量）
    # ------------------------------------------------------------------
    @classmethod
    def _channel_settings(cls, channel: str) -> dict:
        if channel == CHANNEL_EMAIL:
            return {
                "recipients": [x for x in getattr(settings, "EMAIL_SEND_LIST", "").split(",") if x],
                "sender_name": getattr(settings, "EMAIL_SENDER_NAME", "Admin"),
            }
        if channel == CHANNEL_DINGTALK:
            return {
                "webhook": getattr(settings, "DINGTALK_WEBHOOK", ""),
                "secret": getattr(settings, "DINGTALK_SECRET", ""),
            }
        if channel == CHANNEL_FEISHU:
            return {
                "webhook": getattr(settings, "FEISHU_WEBHOOK", ""),
                "secret": getattr(settings, "FEISHU_SECRET", ""),
            }
        if channel == CHANNEL_WECHAT:
            return {
                "webhook": getattr(settings, "WECHAT_WEBHOOK", ""),
            }
        return {}

    # ------------------------------------------------------------------
    # 各渠道实现
    # ------------------------------------------------------------------
    @classmethod
    def _send_email(cls, title, content, level, context) -> tuple[bool, str | None]:
        cfg = cls._channel_settings(CHANNEL_EMAIL)
        recipients = cfg.get("recipients", [])
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
    def _send_dingtalk(cls, title, content, level, context) -> tuple[bool, str | None]:
        cfg = cls._channel_settings(CHANNEL_DINGTALK)
        webhook = cfg.get("webhook", "")
        if not webhook:
            return False, "钉钉 webhook 未配置 (DINGTALK_WEBHOOK)"
        try:
            from framework.notice_utils.dingtalk_control import DingTalkSendMsg

            msg = cls._format_markdown(title, content, level, context)
            DingTalkSendMsg().send_markdown(title=f"[{level.upper()}] {title}", msg=msg)
            return True, None
        except Exception as exc:
            return False, str(exc)

    @classmethod
    def _send_feishu(cls, title, content, level, context) -> tuple[bool, str | None]:
        cfg = cls._channel_settings(CHANNEL_FEISHU)
        webhook = cfg.get("webhook", "")
        if not webhook:
            return False, "飞书 webhook 未配置 (FEISHU_WEBHOOK)"
        try:
            from framework.notice_utils.feishu_control import FeiShuTalkChatBot

            msg = cls._format_content(title, content, level, context)
            FeiShuTalkChatBot().send_text(msg)
            return True, None
        except Exception as exc:
            return False, str(exc)

    @classmethod
    def _send_wechat(cls, title, content, level, context) -> tuple[bool, str | None]:
        cfg = cls._channel_settings(CHANNEL_WECHAT)
        webhook = cfg.get("webhook", "")
        if not webhook:
            return False, "企业微信 webhook 未配置 (WECHAT_WEBHOOK)"
        try:
            from framework.notice_utils.wechat_send_control import WeChatSend

            msg = cls._format_markdown(title, content, level, context)
            WeChatSend(webhook=webhook).send_markdown(msg)
            return True, None
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------
    @staticmethod
    def _format_content(title, content, level, context) -> str:
        lines = [
            f"告警标题: {title}",
            f"告警级别: {level.upper()}",
            f"告警内容: {content}",
        ]
        if context:
            lines.append(f"上下文: {json.dumps(context, ensure_ascii=False, default=str)}")
        return "\n".join(lines)

    @staticmethod
    def _format_markdown(title, content, level, context) -> str:
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
