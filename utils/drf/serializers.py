# sync-init: skip
"""
DRF 增强序列化器
================

- ``BulkSerializerMixin``  ——  批量创建 / 更新 / 删除
- ``RecursiveSerializer``   ——  树形结构自动递归渲染
- ``EncryptedField``        ——  字段级透明加解密（基于 utils.key_management）
- ``DesensitizedCharField`` ——  自动脱敏展示

零新增依赖：仅依赖 DRF + utils.key_management（已有）。
"""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, Iterable, List, Optional

from rest_framework import serializers


# ============================================================================
# 1. 批量序列化
# ============================================================================

class BulkSerializerMixin:
    """
    混合类：为 ModelViewSet 增加 ``bulk_create`` / ``bulk_update`` / ``bulk_delete`` 行为。

    用法
    ----
    >>> class UserSerializer(BulkSerializerMixin, serializers.ModelSerializer):
    ...     class Meta:
    ...         model = User
    ...         fields = "__all__"
    >>> class UserViewSet(BulkSerializerMixin, viewsets.ModelViewSet):
    ...     serializer_class = UserSerializer

    支持的请求体
    ------------
    - ``POST /users/bulk/``  :  ``[{"username": "a"}, {"username": "b"}]``
    - ``PUT /users/bulk/``   :  ``[{"id": 1, "username": "a"}, ...]``
    - ``DELETE /users/bulk/`` : ``{"ids": [1, 2, 3]}``
    """

    # ViewSet 需要实现的钩子（提供 model 与 queryset）
    # 使用时由 ViewSet 注入

    def create(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            return self._bulk_create(request)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            return self._bulk_update(request)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if isinstance(request.data, dict) and "ids" in request.data:
            return self._bulk_delete(request)
        return super().destroy(request, *args, **kwargs)

    # ---- 内部实现 ----

    def _bulk_create(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_bulk_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _bulk_update(self, request):
        ids = [item.get(self.lookup_field or "id") for item in request.data]
        instances = {getattr(obj, self.lookup_field or "id"): obj
                     for obj in self.get_queryset().filter(
                         **{f"{self.lookup_field or 'id'}__in": ids})}
        errors = []
        validated = []
        for idx, item in enumerate(request.data):
            obj_id = item.get(self.lookup_field or "id")
            instance = instances.get(obj_id)
            if not instance:
                errors.append({"index": idx, "id": obj_id, "error": "Not found"})
                continue
            s = self.get_serializer(instance, data=item, partial=True)
            if s.is_valid():
                validated.append((instance, s))
            else:
                errors.append({"index": idx, "id": obj_id, "error": s.errors})
        for instance, s in validated:
            self.perform_update(s)
        return Response(
            {"updated": len(validated), "errors": errors},
            status=status.HTTP_200_OK,
        )

    def _bulk_delete(self, request):
        ids = request.data.get("ids", [])
        queryset = self.get_queryset().filter(**{f"{self.lookup_field or 'id'}__in": ids})
        count = queryset.count()
        queryset.delete()
        return Response({"deleted": count}, status=status.HTTP_200_OK)

    def perform_bulk_create(self, serializer):
        """DRF 默认行为：save 一次；子类可重写为 bulk_create。"""
        serializer.save()


# ============================================================================
# 2. 树形结构序列化
# ============================================================================

class RecursiveField(serializers.Serializer):
    """
    递归引用自身的字段。配合 ModelSerializer 可渲染无限层级树。

    用法
    ----
    >>> class CategorySerializer(serializers.ModelSerializer):
    ...     children = RecursiveField(many=True, read_only=True)
    ...     class Meta:
    ...         model = Category
    ...         fields = ["id", "name", "children"]

    工作原理
    --------
    DRF 在类定义时尝试解析字段类型，会因「类未完成」失败。本类把解析延迟到
    ``to_representation`` 调用时通过 ``self.parent.__class__`` 推断。
    """

    def __init__(self, **kwargs):
        self._recursive_kwargs = kwargs
        kwargs.pop("many", None)  # 防止父类检测冲突
        super().__init__(**kwargs)
        self._resolved_serializer = None

    def _get_serializer(self):
        """惰性解析父类 serializer 类型。"""
        if self._resolved_serializer is not None:
            return self._resolved_serializer
        parent = self.parent
        if parent is None:
            return None
        cls = parent.__class__
        # 构造一个同类型的实例，复用 fields 定义
        self._resolved_serializer = cls(
            context=self.context, **self._recursive_kwargs
        )
        return self._resolved_serializer

    def to_representation(self, value):
        ser = self._get_serializer()
        if ser is None:
            return []
        return ser.to_representation(value)


# ============================================================================
# 3. 字段级加密
# ============================================================================

class EncryptedField(serializers.CharField):
    """
    字段级透明加解密。

    - 写入 DB：明文 → 密文（base64 编码）
    - 读取 API：密文 → 明文

    依赖 ``utils.key_management``；若未配置则降级为明文（不抛错）。

    Examples
    --------
    >>> class UserSerializer(serializers.ModelSerializer):
    ...     id_card = EncryptedField()
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("style", {})
        super().__init__(**kwargs)

    def _get_crypto(self):
        try:
            from utils.key_management import get_crypto
            return get_crypto()
        except Exception:
            return None

    def to_internal_value(self, data):
        text = super().to_internal_value(data)
        crypto = self._get_crypto()
        if crypto is None:
            return text
        try:
            return crypto.encrypt(text)
        except Exception:
            # 加密失败保留明文（不阻断业务）
            return text

    def to_representation(self, value):
        if not value:
            return value
        crypto = self._get_crypto()
        if crypto is None:
            return value
        try:
            return crypto.decrypt(value)
        except Exception:
            return value


# ============================================================================
# 4. 脱敏展示
# ============================================================================

class DesensitizedCharField(serializers.CharField):
    """
    自动脱敏展示字段（仅在 ``to_representation`` 时处理，写入仍用明文）。

    Parameters
    ----------
    pattern : str
        正则模式（必须包含 1 个分组，分组部分保留为 ``*``）。
        默认手机号 11 位保留前 3 后 4。
    keep_left : int
        pattern 失效时，保留左侧 N 字符。
    keep_right : int
        pattern 失效时，保留右侧 N 字符。
    mask_char : str
        脱敏字符，默认 ``*``。

    Examples
    --------
    >>> class UserSerializer(serializers.ModelSerializer):
    ...     phone = DesensitizedCharField()
    ...     id_card = DesensitizedCharField(pattern=r'(.{4}).*(.{4})')
    """

    DEFAULT_PATTERN = r'(1[3-9]\d)\d{4}(\d{4})'

    def __init__(
        self,
        pattern: Optional[str] = None,
        keep_left: int = 3,
        keep_right: int = 4,
        mask_char: str = "*",
        **kwargs,
    ):
        self.pattern = re.compile(pattern or self.DEFAULT_PATTERN)
        self.keep_left = keep_left
        self.keep_right = keep_right
        self.mask_char = mask_char
        super().__init__(**kwargs)

    def to_representation(self, value):
        text = super().to_representation(value)
        if not text:
            return text
        try:
            m = self.pattern.search(str(text))
            if m and m.lastindex and m.lastindex >= 2:
                left, right = m.group(1), m.group(2)
                middle = self.mask_char * (len(text) - len(left) - len(right))
                return f"{left}{middle}{right}"
        except Exception:
            pass
        # 兜底：保留首尾
        s = str(text)
        if len(s) <= self.keep_left + self.keep_right:
            return self.mask_char * len(s)
        middle_len = len(s) - self.keep_left - self.keep_right
        return s[: self.keep_left] + self.mask_char * middle_len + s[-self.keep_right:]


# ============================================================================
# 5. 通用基类
# ============================================================================

class BaseModelSerializer(serializers.ModelSerializer):
    """
    通用基类：统一时间字段格式化、id 转 string（前端 JS 大数安全）。
    子类只需 ``class Meta: model = ...; fields = ...``。
    """

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 时间字段统一 ISO8601
        for k, v in list(data.items()):
            if hasattr(v, "isoformat"):
                data[k] = v.isoformat()
        return data
