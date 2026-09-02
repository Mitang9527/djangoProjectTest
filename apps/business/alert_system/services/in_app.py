"""
站内信服务 — 落库到 InAppMessage 的站内通知。

与 NotificationDispatcher（外部渠道：邮件/钉钉/飞书）互补：
- 站内信面向登录用户收件箱，不依赖外部 webhook/凭据，天然可达。
- 支持按 MessageTemplate.code 渲染发送（{placeholder} 占位符）。
- 写操作均为原子 create / bulk_create，不产生异步任务，调用方同步感知结果。

用法:
    from business.alert_system.services import InAppNotificationService

    InAppNotificationService.send_to_user(user, "标题", "内容")
    InAppNotificationService.send_by_template(
        user, "quota_warning", context={"tenant": "demo", "usage": "85%"}
    )
"""
from __future__ import annotations

from typing import Iterable

from ..models import InAppMessage, MessageTemplate


class InAppNotificationService:
    """站内信服务"""

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    @classmethod
    def send_to_user(
        cls,
        user,
        title: str,
        content: str,
        level: str = "info",
        tenant=None,
    ) -> InAppMessage:
        """给单个用户发送一条站内信"""
        return InAppMessage.objects.create(
            user=user,
            tenant=tenant,
            title=title,
            content=content,
            level=level,
        )

    @classmethod
    def send_to_users(
        cls,
        users: Iterable,
        title: str,
        content: str,
        level: str = "info",
        tenant=None,
    ) -> list[InAppMessage]:
        """批量发送（单个用户列表时使用 bulk_create，减少写放大）"""
        users = list(users)
        if not users:
            return []
        if len(users) == 1:
            return [cls.send_to_user(users[0], title, content, level, tenant)]
        messages = [
            InAppMessage(user=u, tenant=tenant, title=title, content=content, level=level)
            for u in users
        ]
        return InAppMessage.objects.bulk_create(messages)

    @classmethod
    def send_by_template(
        cls,
        user,
        template_code: str,
        context: dict | None = None,
        level: str = "info",
        tenant=None,
    ) -> InAppMessage | None:
        """
        按模板渲染并发送。

        template.content / template.title 中的 {name} 占位符
        由 context 同名键替换（str.format 语义，缺失键抛 KeyError 由调用方处理）。

        Returns:
            发送成功返回 InAppMessage；模板不存在或未启用返回 None。
        """
        template = MessageTemplate.objects.filter(
            code=template_code, is_active=True
        ).first()
        if template is None:
            return None
        ctx = context or {}
        title = template.title.format(**ctx)
        content = template.content.format(**ctx)
        return cls.send_to_user(user, title, content, level, tenant)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @classmethod
    def unread_count(cls, user) -> int:
        """用户未读站内信数量"""
        return InAppMessage.objects.filter(user=user, read_at__isnull=True).count()
