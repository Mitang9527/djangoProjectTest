# sync-init: skip
"""
版本管理 - DRF 集成
====================

- VersionedAPIView：基类，自动读取 request.api_version
- VersionedMixin：混入已有 APIView / ViewSet
- VersionedViewSet：带版本感知的 ViewSet
"""
from __future__ import annotations

import logging
from typing import Optional

from .core import get_registry
from .decorators import _check_version_constraints

logger = logging.getLogger(__name__)


class VersionedMixin:
    """
    DRF 视图混入：自动校验方法级版本约束（基于 @versioned_view 标注）。

    注：本混入在导入时不触发 DRF settings 访问。DRF 父类（APIView/ViewSet）
    需由用户在视图层 import 后再混入。

    用法::

        from rest_framework.views import APIView
        from framework.versioning.drf import VersionedMixin

        class MyView(VersionedMixin, APIView):
            @versioned_view(min_version="v2")
            def get(self, request):
                ...
    """
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        return response

    def get_version_metadata(self, version: Optional[str] = None) -> dict:
        v = version or getattr(self.request, "api_version", None)
        if not v:
            return {"version": None, "status": "unknown"}
        spec = get_registry().get(v)
        if not spec:
            return {"version": v, "status": "unknown"}
        return {
            "version": v,
            "status": spec.status.value,
            "is_default": spec.is_default,
            "is_deprecated": spec.is_deprecated(),
            "successor": spec.successor,
        }


# 延迟绑定 DRF 基类（仅在用户实际继承时才触发）
def _make_api_view():
    """工厂：创建带 DRF APIView 的子类"""
    from rest_framework.views import APIView
    return type("VersionedAPIView", (VersionedMixin, APIView), {})


def _make_viewset():
    """工厂：创建带 DRF ViewSet 的子类"""
    from rest_framework.viewsets import ViewSet
    return type("VersionedViewSet", (VersionedMixin, ViewSet), {})


# 用户可调用这两个工厂获取具体类；或自己组合 VersionedMixin + APIView
VersionedAPIView = None  # 延迟创建
VersionedViewSet = None


def _ensure_drf_subclasses():
    global VersionedAPIView, VersionedViewSet
    if VersionedAPIView is None:
        VersionedAPIView = _make_api_view()
    if VersionedViewSet is None:
        VersionedViewSet = _make_viewset()


def get_versioned_api_view():
    """获取 VersionedAPIView 类（首次调用时初始化）"""
    _ensure_drf_subclasses()
    return VersionedAPIView


def get_versioned_viewset():
    """获取 VersionedViewSet 类（首次调用时初始化）"""
    _ensure_drf_subclasses()
    return VersionedViewSet

