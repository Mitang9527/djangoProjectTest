# sync-init: skip
"""
ORM 增强
========

零依赖。

- ``SoftDeleteModel``       ——  软删除（deleted_at 字段）
- ``OptimisticLockMixin``   ——  乐观锁（version 字段）
- ``bulk_create_or_update`` ——  批量 upsert（``update_or_create`` 的批量版）
- ``TenantScopedQuerySet``  ——  租户过滤（依赖 request.tenant）

Examples
--------
>>> class Article(SoftDeleteModel):
...     title = models.CharField(max_length=100)
>>> Article.objects.create(title="a")
>>> Article.objects.all().count()            # 包含软删除
2
>>> Article.objects.alive().count()          # 仅未删除
1
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional, Type

from django.db import models, transaction
from django.utils import timezone


# ============================================================================
# 1. 软删除
# ============================================================================

class SoftDeleteQuerySet(models.QuerySet):
    """支持 alive() / dead() / delete(soft=True) 的 QuerySet。"""

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self, soft: bool = True):
        """
        默认软删除。传 ``soft=False`` 则硬删除。
        """
        if soft:
            return super().update(deleted_at=timezone.now())
        return super().delete()

    def hard_delete(self):
        return super().delete()

    def restore(self):
        return super().update(deleted_at=None)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """默认 Manager：自动 alive() 过滤。"""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """不过滤 deleted_at 的 Manager，可访问 ``Article.all_objects.dead()``。"""


class SoftDeleteModel(models.Model):
    """
    软删除基类。

    用法
    ----
    >>> class Article(SoftDeleteModel):
    ...     title = models.CharField(max_length=100)
    >>> # 默认 manager 过滤掉已删除
    >>> Article.objects.all()
    >>> # 全量访问
    >>> Article.all_objects.all()
    >>> # 软删
    >>> article.delete()
    >>> # 恢复
    >>> article.restore()
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, soft: bool = True, keep_parents: bool = False):
        if soft:
            if self.pk is None:
                return (0, {self._meta.label: 0})
            type(self).all_objects.filter(pk=self.pk).update(deleted_at=timezone.now())
            self.deleted_at = timezone.now()
            return (1, {self._meta.label: 1})
        return super().delete(using=using, keep_parents=keep_parents)

    def hard_delete(self, using=None, keep_parents: bool = False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self, using=None):
        if self.pk is None:
            return
        type(self).all_objects.filter(pk=self.pk).update(deleted_at=None)
        self.deleted_at = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# ============================================================================
# 2. 乐观锁
# ============================================================================

class OptimisticLockMixin(models.Model):
    """
    乐观锁。每次 save() 自增 version。``save()`` 时若 version 与 DB 不一致则抛
    ``ConcurrentModificationError``。
    """
    version = models.PositiveIntegerField(default=1, db_index=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # 已存在的对象（pk 不为空）才检查乐观锁
        if self.pk and self._state.adding is False:
            current = type(self).objects.filter(pk=self.pk).values_list(
                "version", flat=True
            ).first()
            if current is None:
                # 已被并发删除
                raise ConcurrentModificationError(
                    f"{type(self).__name__}(pk={self.pk}) 不存在"
                )
            if current != self.version:
                raise ConcurrentModificationError(
                    f"{type(self).__name__}(pk={self.pk}) 已被并发修改: "
                    f"db version={current}, current version={self.version}"
                )
            self.version = current + 1
        super().save(*args, **kwargs)


class ConcurrentModificationError(Exception):
    """乐观锁冲突。"""


# ============================================================================
# 3. 批量 upsert
# ============================================================================

def bulk_create_or_update(
    model: Type[models.Model],
    objs: Iterable[models.Model],
    *,
    update_fields: Optional[List[str]] = None,
    unique_fields: Optional[List[str]] = None,
    batch_size: Optional[int] = None,
) -> List[models.Model]:
    """
    批量 ``update_or_create``。基于唯一键判断存在性。

    Parameters
    ----------
    model : Model class
    objs : iterable of Model instances
    update_fields : list of str
        已存在时更新哪些字段；默认更新除主键+unique_fields 外的所有字段
    unique_fields : list of str
        唯一键字段；默认取 ``_meta.unique_together`` 第一组 + ``unique=True`` 字段
    batch_size : int
        每批大小

    Returns
    -------
    list of saved instances
    """
    objs = list(objs)
    if not objs:
        return []

    if unique_fields is None:
        unique_fields = _infer_unique_fields(model)

    all_field_names = [f.name for f in model._meta.fields]
    if update_fields is None:
        update_fields = [
            f for f in all_field_names
            if f not in unique_fields and f != model._meta.pk.name
        ]

    saved: List[models.Model] = []
    with transaction.atomic():
        for obj in objs:
            lookup = {f: getattr(obj, f) for f in unique_fields}
            if None in lookup.values():
                # 唯一键未填 → 直接 create
                obj.save()
                saved.append(obj)
                continue
            try:
                existing = model.objects.get(**lookup)
            except model.DoesNotExist:
                obj.save()
                saved.append(obj)
                continue
            for f in update_fields:
                setattr(existing, f, getattr(obj, f))
            existing.save()
            saved.append(existing)
    return saved


def _infer_unique_fields(model: Type[models.Model]) -> List[str]:
    """从 model meta 推断唯一键。"""
    candidates = []
    for f in model._meta.fields:
        if f.unique and f.name != model._meta.pk.name:
            candidates.append(f.name)
    for group in model._meta.unique_together:
        if len(group) == 1:
            candidates.append(group[0])
    # 去重保序
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


# ============================================================================
# 4. 租户隔离
# ============================================================================

class TenantScopedQuerySet(models.QuerySet):
    """按 request.tenant 过滤的 QuerySet。"""
    def for_tenant(self, tenant):
        if tenant is None:
            return self.none()
        return self.filter(tenant=tenant)


class TenantScopedManager(models.Manager.from_queryset(TenantScopedQuerySet)):
    pass


def get_request_tenant():
    """从当前线程 / 请求中提取 tenant（中间件已注入）。"""
    try:
        from threading import current_thread
        return getattr(current_thread(), "current_tenant", None)
    except Exception:
        return None


# ============================================================================
# 5. 便捷混入：自动维护 created_at / updated_at
# ============================================================================

class TimestampMixin(models.Model):
    """自动维护创建/更新时间。"""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ============================================================================
# 6. 链式示例：组合能力
# ============================================================================

class BaseModel(TimestampMixin, OptimisticLockMixin, SoftDeleteModel):
    """
    推荐的标准基类：时间戳 + 乐观锁 + 软删除。

    用法
    ----
    >>> class Order(BaseModel):
    ...     amount = models.DecimalField(max_digits=10, decimal_places=2)
    """
    class Meta:
        abstract = True
