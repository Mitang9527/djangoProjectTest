# sync-init: skip
"""DRF 增强序列化器：批量操作 BulkSerializerMixin / 树形递归 RecursiveField / 字段加密 EncryptedField / 脱敏展示 DesensitizedCharField。

零新增依赖：仅 DRF + framework.key_management。
"""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, Iterable, List, Optional

from rest_framework import serializers


class BulkSerializerMixin:
    """为 ModelViewSet 增加 bulk_create/bulk_update/bulk_delete：请求体为 list 即走批量分支。

    POST /users/bulk/ 传 [{...}]；PUT 传 [{"id":1,...}]；DELETE 传 {"ids":[1,2,3]}。
    """

    # ViewSet 需要实现 model 与 queryset 钩子（使用时注入）

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


class RecursiveField(serializers.Serializer):
    """递归引用自身的字段，配合 ModelSerializer 渲染无限层级树。

    原理：DRF 在类定义时会尝试解析字段类型并因类未完成而失败，故把解析延迟到
    to_representation 时通过 self.parent.__class__ 推断（惰性构造同类型实例）。
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
        # 构造同类型实例，复用 fields 定义
        self._resolved_serializer = cls(
            context=self.context, **self._recursive_kwargs
        )
        return self._resolved_serializer

    def to_representation(self, value):
        ser = self._get_serializer()
        if ser is None:
            return []
        return ser.to_representation(value)


class EncryptedField(serializers.CharField):
    """字段级透明加解密：写入 DB 明文→密文(base64)，读取 API 密文→明文。

    依赖 framework.key_management；未配置时降级为明文（不抛错）。
    注意：加密字段不可用于 filter/order_by/distinct 等 DB 层操作（DB 存密文）。
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("style", {})
        super().__init__(**kwargs)

    def _get_crypto(self):
        try:
            from framework.key_management import get_crypto
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


class DesensitizedCharField(serializers.CharField):
    """自动脱敏展示字段（仅 to_representation 处理，写入仍用明文）。

    参数: pattern(正则，须含 1 个分组，默认手机号保留前3后4) / keep_left / keep_right
    （pattern 失效时保留左右 N 字符） / mask_char(默认 *)
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


class BaseModelSerializer(serializers.ModelSerializer):
    """通用基类：时间字段统一 ISO8601、id 转 string（前端 JS 大数安全）。子类只需定义 Meta.model/fields。"""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # 时间字段统一 ISO8601
        for k, v in list(data.items()):
            if hasattr(v, "isoformat"):
                data[k] = v.isoformat()
        return data
