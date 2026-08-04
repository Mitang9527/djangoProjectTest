"""
告警系统 — DRF 视图

4 个 ViewSet (CRUD) + 自定义 action:
- AlertRuleViewSet:            规则管理 + trigger(手动触发)
- AlertSilenceViewSet:         静默管理
- AlertHistoryViewSet:         历史查询(只读) + acknowledge + resolve + trigger
- AlertNotificationConfigViewSet: 渠道配置 + test(测试发送)

+ 函数视图: alert_stats (统计面板)
"""

from rest_framework import status, viewsets, filters as drf_filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django_filters.rest_framework import DjangoFilterBackend

from djangoProjectTest.viewsets import BaseModelViewSet
from djangoProjectTest.pagination import StandardPagination

from .models import (
    AlertRule,
    AlertSilence,
    AlertHistory,
    AlertNotificationConfig,
)
from .serializers import (
    AlertRuleSerializer,
    AlertSilenceSerializer,
    AlertHistorySerializer,
    AlertNotificationConfigSerializer,
    AcknowledgeActionSerializer,
    ResolveActionSerializer,
    TriggerAlertSerializer,
    TestNotifySerializer,
)
from .services import AlertEngine, NotificationDispatcher


# ---------------------------------------------------------------
# ViewSets
# ---------------------------------------------------------------

class AlertRuleViewSet(BaseModelViewSet):
    """告警规则管理"""

    queryset = AlertRule.objects.select_related("created_by").all()
    serializer_class = AlertRuleSerializer
    filterset_fields = ["enabled", "level", "condition_type"]
    search_fields = ["name", "description", "condition_value"]
    ordering_fields = ["created_at", "updated_at", "level"]
    ordering = ["-created_at"]


class AlertSilenceViewSet(BaseModelViewSet):
    """告警静默管理"""

    queryset = AlertSilence.objects.select_related("rule", "created_by").all()
    serializer_class = AlertSilenceSerializer
    filterset_fields = ["enabled", "rule"]
    search_fields = ["name", "description", "match_pattern"]
    ordering_fields = ["created_at", "start_time", "end_time"]
    ordering = ["-created_at"]


class AlertHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    告警历史记录 — 只读 + 确认/解决/触发。

    继承 ReadOnlyModelViewSet（只有 list/retrieve），
    额外提供 acknowledge / resolve / trigger 三个自定义 action。
    """

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]

    queryset = AlertHistory.objects.select_related(
        "rule", "acknowledged_by", "resolved_by"
    ).all()
    serializer_class = AlertHistorySerializer
    filterset_fields = ["level", "status", "acknowledged", "resolved", "rule"]
    search_fields = ["title", "content"]
    ordering_fields = ["first_occurred_at", "last_occurred_at", "occurrences"]
    ordering = ["-first_occurred_at"]

    # ---- 自定义 Action ----

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, pk=None):
        """确认告警"""
        history = self.get_object()
        if history.acknowledged:
            return Response(
                {"detail": "该告警已被确认"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = AcknowledgeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = AlertEngine.acknowledge(history.pk, request.user)
        return Response(
            AlertHistorySerializer(result).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request, pk=None):
        """解决告警"""
        history = self.get_object()
        if history.resolved:
            return Response(
                {"detail": "该告警已被解决"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ResolveActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = AlertEngine.resolve(history.pk, request.user)
        return Response(
            AlertHistorySerializer(result).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="trigger")
    def trigger(self, request):
        """手动触发告警"""
        serializer = TriggerAlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        rule = None
        if data.get("rule_id"):
            try:
                rule = AlertRule.objects.get(pk=data["rule_id"])
            except AlertRule.DoesNotExist:
                return Response(
                    {"detail": f"规则 {data['rule_id']} 不存在"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        history = AlertEngine.trigger(
            title=data["title"],
            content=data["content"],
            rule=rule,
            level=data["level"],
            channels=data.get("channels") or (rule.channels if rule else []),
            context=data.get("context", {}),
        )
        return Response(
            AlertHistorySerializer(history).data,
            status=status.HTTP_201_CREATED,
        )


class AlertNotificationConfigViewSet(BaseModelViewSet):
    """通知渠道配置"""

    queryset = AlertNotificationConfig.objects.all()
    serializer_class = AlertNotificationConfigSerializer
    filterset_fields = ["channel", "enabled", "is_default"]
    search_fields = ["name"]
    ordering_fields = ["created_at", "channel"]
    ordering = ["-created_at"]

    @action(detail=False, methods=["post"], url_path="test")
    def test_notify(self, request):
        """测试通知渠道连通性"""
        serializer = TestNotifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        results = NotificationDispatcher.dispatch(
            channels=[data["channel"]],
            title=data["title"],
            content=data["content"],
            level="info",
            context={"source": "test_notify", "user": request.user.username},
        )

        channel_result = results.get(data["channel"], {})
        http_status = (
            status.HTTP_200_OK
            if channel_result.get("success")
            else status.HTTP_502_BAD_GATEWAY
        )
        return Response(
            {
                "channel": data["channel"],
                "success": channel_result.get("success", False),
                "error": channel_result.get("error"),
            },
            status=http_status,
        )


# ---------------------------------------------------------------
# 函数视图
# ---------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def alert_stats(request):
    """告警统计面板数据"""
    stats = AlertEngine.get_stats()
    return Response(stats)
