"""
统一 ViewSet 基类 — 为所有 DRF ViewSet 提供一致的默认行为。

用法:
    from djangoProjectTest.viewsets import BaseModelViewSet

    class TenantViewSet(BaseModelViewSet):
        queryset = Tenant.objects.all()
        serializer_class = TenantSerializer
        # 自动获得: IsAuthenticated + 分页 + 过滤 + 搜索 + 排序

特性:
- 内置 IsAuthenticated 认证
- 自动启用分页 (默认 20/页)
- 自动集成 DjangoFilterBackend / SearchFilter / OrderingFilter
- perform_create 自动注入 created_by (如果有该字段)
- 预留审计日志钩子
"""

from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, permissions, viewsets

from djangoProjectTest.pagination import StandardPagination


# ---------------------------------------------------------------
# BaseModelViewSet
# ---------------------------------------------------------------

class BaseModelViewSet(viewsets.ModelViewSet):
    """
    项目级统一 ViewSet 基类。

    自动提供:
    - 认证: IsAuthenticated
    - 分页: StandardPagination
    - 过滤: DjangoFilterBackend + SearchFilter + OrderingFilter
    - created_by 自动注入 (model 有 created_by 字段时)

    子类只需覆盖三个必要属性:
    - queryset
    - serializer_class
    - filterset_fields / search_fields / ordering_fields (可选)
    """

    # ---- 权限 ----
    permission_classes = [permissions.IsAuthenticated]

    # ---- 分页 ----
    pagination_class = StandardPagination

    # ---- 过滤 & 搜索 & 排序 ----
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    # 子类按需覆盖以下字段:
    filterset_fields: list[str] = []
    search_fields: list[str] = []
    ordering_fields: list[str] = []
    ordering: list[str] = ["-id"]

    # -----------------------------------------------------------
    # CRUD 钩子
    # -----------------------------------------------------------

    def perform_create(self, serializer):
        """自动注入 created_by 字段 (如果 model 有该字段且请求已认证)"""
        instance = serializer.save()
        self._maybe_set_created_by(instance)
        self._log_action("CREATE", instance)
        return instance

    def perform_update(self, serializer):
        instance = serializer.save()
        self._maybe_set_updated_by(instance)
        self._log_action("UPDATE", instance)
        return instance

    def perform_destroy(self, instance):
        self._log_action("DELETE", instance)
        instance.delete()

    # -----------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------

    def _maybe_set_created_by(self, instance) -> None:
        """如果 model 有 created_by 字段, 自动设为当前用户"""
        if (
            hasattr(instance, "created_by")
            and self.request
            and self.request.user.is_authenticated
        ):
            # 只有为空时才设置 (允许显式传入)
            if instance.created_by is None or instance.created_by == "":
                instance.created_by = self.request.user
                instance.save(update_fields=["created_by"])
    
    def _maybe_set_updated_by(self, instance) -> None:
        """如果 model 有 updated_by 字段, 自动设为当前用户"""
        if (
            hasattr(instance, "updated_by")
            and self.request
            and self.request.user.is_authenticated
        ):
            instance.updated_by = self.request.user
            instance.save(update_fields=["updated_by"])

    def _log_action(self, action: str, instance) -> None:
        """
        审计日志钩子 — 默认记录到 loguru。
        如需写入数据库的 AuditLog 表，子类覆盖此方法。
        """
        from loguru import logger

        try:
            model_name = instance._meta.model_name
            pk = getattr(instance, "pk", None)
            user = (
                self.request.user.username
                if self.request and self.request.user.is_authenticated
                else "anonymous"
            )
            logger.info(f"[AUDIT] {user} {action} {model_name}#{pk}")
        except Exception:
            pass  # 审计日志失败不影响主流程


# ---------------------------------------------------------------
# 无分页 ViewSet (用于下拉框等场景)
# ---------------------------------------------------------------

class BaseReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """只读 ViewSet 基类 — 无分页, 适合下拉选项/字典数据"""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields: list[str] = []
    search_fields: list[str] = []
    ordering_fields: list[str] = []
    ordering: list[str] = ["-id"]
