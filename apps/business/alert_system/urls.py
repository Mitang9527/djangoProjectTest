"""
告警系统 — 路由配置

自动发现机制会将本文件注册到 /api/alert_system/ 下，
因此本文件中的路径直接从根开始（不需要再加 api/ 前缀）。

路由表:
    /api/alert_system/rules/                     → AlertRuleViewSet
    /api/alert_system/silences/                   → AlertSilenceViewSet
    /api/alert_system/histories/                  → AlertHistoryViewSet (只读)
    /api/alert_system/histories/{id}/acknowledge/ → 确认告警
    /api/alert_system/histories/{id}/resolve/     → 解决告警
    /api/alert_system/histories/trigger/          → 手动触发告警
    /api/alert_system/notification-configs/       → AlertNotificationConfigViewSet
    /api/alert_system/notification-configs/test/  → 测试通知渠道
    /api/alert_system/stats/                      → 告警统计面板
    /api/alert_system/message-templates/          → MessageTemplateViewSet (模板)
    /api/alert_system/in-app-messages/            → InAppMessageViewSet (站内信)
    /api/alert_system/in-app-messages/unread_count/ → 未读数
    /api/alert_system/in-app-messages/read_all/   → 全部已读
    /api/alert_system/in-app-messages/{id}/mark_read/ → 单条已读
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AlertRuleViewSet,
    AlertSilenceViewSet,
    AlertHistoryViewSet,
    AlertNotificationConfigViewSet,
    MessageTemplateViewSet,
    InAppMessageViewSet,
    alert_stats,
)

app_name = "alert_system"

router = DefaultRouter()
router.register(r"rules", AlertRuleViewSet, basename="alert-rule")
router.register(r"silences", AlertSilenceViewSet, basename="alert-silence")
router.register(r"histories", AlertHistoryViewSet, basename="alert-history")
router.register(
    r"notification-configs",
    AlertNotificationConfigViewSet,
    basename="alert-notification-config",
)
router.register(
    r"message-templates",
    MessageTemplateViewSet,
    basename="message-template",
)
router.register(
    r"in-app-messages",
    InAppMessageViewSet,
    basename="in-app-message",
)

urlpatterns = [
    path("", include(router.urls)),
    path("stats/", alert_stats, name="alert-stats"),
]
