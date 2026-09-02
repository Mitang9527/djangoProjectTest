"""
参考完整性守卫（对齐 Fast-Vben-Admin ``reference_guards.py`` 的引用注册表模式）。

问题背景：删除被业务数据引用的对象时，裸依赖 DB 外键约束会得到不可读的
``IntegrityError``（500）。本模块用"声明式引用注册表"在业务层拦截：

    - 业务 app 在 ``AppConfig.ready()`` 中调用 :func:`register_references` 声明引用关系；
    - ViewSet 混入 :class:`ReferenceGuardMixin`（或显式调用 :func:`assert_no_references`）
      在 destroy 前检查，有引用则抛 :class:`ReferenceConflict`（DRF 层转 409）。

用法::

    # apps/system/saas/apps.py
    def ready(self):
        from framework.db.reference_guards import register_references
        from system.saas import models as m
        register_references(m.Role, [
            (m.User, ("role",)),
            (m.TenantMember, ("role",)),
        ])

    # viewsets.py
    class PermissionViewSet(ReferenceGuardMixin, BaseModelViewSet):
        ...

    # 已有自定义 destroy 的 ViewSet 直接调用
    def destroy(self, request, *args, **kwargs):
        assert_no_references(Role, role.pk)
        ...
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.db import models
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

# 目标模型 -> [(引用模型, (FK 字段名, ...)), ...]
_REFERENCE_REGISTRY: dict[type[models.Model], list[tuple[type[models.Model], tuple[str, ...]]]] = {}


class ReferenceConflict(Exception):
    """删除被引用数据时抛出（非 DRF 依赖，供脚本/服务层使用）。"""


class ReferenceConflictError(APIException):
    """DRF 层 409 异常：删除被引用数据时由 :class:`ReferenceGuardMixin` 转换抛出。"""

    status_code = 409
    default_detail = "数据存在引用，不能删除"
    default_code = "reference_conflict"


def register_references(target_model: type[models.Model], refs: Iterable[tuple[type[models.Model], Iterable[str]]]) -> None:
    """为 ``target_model`` 注册一组引用关系（可重复调用，追加合并）。"""
    if target_model not in _REFERENCE_REGISTRY:
        _REFERENCE_REGISTRY[target_model] = []
    for ref_model, fk_fields in refs:
        fields = tuple(fk_fields)
        _REFERENCE_REGISTRY[target_model].append((ref_model, fields))
    logger.debug("reference_guards: registered %d refs for %s", len(list(refs)), target_model.__name__)


def get_references(target_model: type[models.Model]) -> list[tuple[type[models.Model], tuple[str, ...]]]:
    """返回目标模型的已注册引用列表。"""
    return _REFERENCE_REGISTRY.get(target_model, [])


def assert_no_references(target_model: type[models.Model], obj_id, tenant_id=None) -> None:
    """
    检查 ``obj_id`` 是否被任何已注册引用模型引用；有引用抛 :class:`ReferenceConflict`。

    ``obj_id`` 兼容 UUID/整型主键。``tenant_id`` 为预留参数（当前不参与过滤，
    UUID 主键全局唯一；整型主键多租户场景可在注册时保证租户内唯一）。
    """
    if not obj_id:
        return
    target_name = getattr(target_model._meta, "verbose_name", None) or target_model.__name__
    for ref_model, fk_fields in get_references(target_model):
        ref_name = getattr(ref_model._meta, "verbose_name", None) or ref_model.__name__
        qs = ref_model.objects
        for field in fk_fields:
            filter_kwargs = {field: obj_id}
            try:
                count = qs.filter(**filter_kwargs).count()
            except Exception as exc:  # pragma: no cover - 防御性兜底
                logger.warning("reference_guards: check %s.%s failed: %s", ref_model.__name__, field, exc)
                continue
            if count:
                raise ReferenceConflict(
                    f"{target_name} 已被 {count} 处{ref_name}引用，不能删除"
                )


def raise_if_referenced(target_model: type[models.Model], obj_id) -> None:
    """DRF 便捷入口：有引用则抛 :class:`ReferenceConflictError`（409），供自定义 destroy 使用。"""
    try:
        assert_no_references(target_model, obj_id)
    except ReferenceConflict as exc:
        # detail 用 {"detail","code"} 结构：CustomRenderer 据此把 code 透出到 errors.error_code
        raise ReferenceConflictError(
            {"detail": str(exc), "code": "reference_conflict"}
        ) from exc


class ReferenceGuardMixin:
    """
    DRF ViewSet 混入：``destroy`` 前自动执行引用完整性检查。

    用法::

        class PermissionViewSet(ReferenceGuardMixin, BaseModelViewSet):
            queryset = Permission.objects.all()
            ...

    默认取 ``queryset.model`` 作为目标模型；自定义目标可设 ``reference_model``。
    已有自定义 ``destroy`` 的 ViewSet（MRO 遮蔽）请直接调用 :func:`assert_no_references`。
    """

    reference_model: type[models.Model] | None = None

    def assert_deletable(self, instance) -> None:
        """引用检查钩子：子类可覆写叠加业务校验（如系统角色保护）。"""
        model = self.reference_model or getattr(self.get_queryset(), "model", None)
        if model is not None:
            assert_no_references(model, instance.pk)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.assert_deletable(instance)
        except ReferenceConflict as exc:
            raise ReferenceConflictError(
                {"detail": str(exc), "code": "reference_conflict"}
            ) from exc
        return super().destroy(request, *args, **kwargs)
