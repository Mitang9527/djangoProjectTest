# sync-init: skip
"""
版本管理 - 装饰器与方法级版本控制
==================================

提供：
- @versioned_view(min_version, removed_in)：方法级版本守卫
- @only_for("v3-beta")：白名单（其他版本 404）
- @since("v2")：自 v2 起可用
- @until("v3")：v3 之前可用
"""
from __future__ import annotations

import functools
import logging
from typing import Callable, Optional

from rest_framework import status as drf_status
from rest_framework.response import Response

from .core import get_registry

logger = logging.getLogger(__name__)


def _resolve_active_version(args, kwargs) -> Optional[str]:
    """
    从装饰函数参数中提取 request，再获取 request.api_version。
    约定：request 是第一个位置参数或 'request' 关键字参数。
    """
    request = kwargs.get("request")
    if request is None and args:
        request = args[0]
    if request is None:
        return None
    return getattr(request, "api_version", None)


def _version_compare(a: str, b: str) -> int:
    """
    版本号字典序比较：v1 < v2 < v2.1 < v2.2 < v3 < v10
    简化实现：拆 v 前缀与数字段
    """
    def parse(v: str) -> tuple:
        m = v.lstrip("v").split("-")[0]
        nums = []
        for part in m.split("."):
            try:
                nums.append(int(part))
            except ValueError:
                nums.append(0)
        return tuple(nums)

    pa, pb = parse(a), parse(b)
    return (pa > pb) - (pa < pb)


def _check_version_constraints(
    active_version: Optional[str],
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
    removed_in: Optional[str] = None,
    only_for: Optional[str] = None,
) -> Optional[Response]:
    """
    返回 None 表示通过；返回 Response 表示拒绝。
    """
    if only_for:
        if active_version != only_for:
            return Response(
                {"detail": f"此接口仅在版本 {only_for} 可用"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

    if active_version is None:
        # 未指定版本：放行（由其他层兜底）
        return None

    if min_version and _version_compare(active_version, min_version) < 0:
        return Response(
            {"detail": f"此接口自版本 {min_version} 起可用"},
            status=drf_status.HTTP_404_NOT_FOUND,
        )

    if max_version and _version_compare(active_version, max_version) > 0:
        return Response(
            {"detail": f"此接口已在版本 {max_version} 之后移除"},
            status=drf_status.HTTP_404_NOT_FOUND,
        )

    if removed_in and _version_compare(active_version, removed_in) >= 0:
        return Response(
            {
                "detail": f"此接口在 {removed_in} 中已移除",
                "successor": get_registry().get(removed_in).successor if get_registry().get(removed_in) else None,
            },
            status=drf_status.HTTP_410_GONE,
        )

    return None


def versioned_view(
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
    removed_in: Optional[str] = None,
    only_for_version: Optional[str] = None,
):
    """
    方法级版本守卫装饰器。

    Example::

        @versioned_view(min_version="v2", removed_in="v4")
        def my_view(request):
            ...

        @versioned_view(only_for_version="v3-beta")
        def experimental(request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            active = _resolve_active_version(args, kwargs)
            blocked = _check_version_constraints(
                active,
                min_version=min_version,
                max_version=max_version,
                removed_in=removed_in,
                only_for=only_for_version,
            )
            if blocked is not None:
                return blocked
            return func(*args, **kwargs)
        wrapper.__versioned__ = {
            "min_version": min_version,
            "max_version": max_version,
            "removed_in": removed_in,
            "only_for": only_for_version,
        }
        return wrapper
    return decorator


def only_for(version: str):
    """仅指定版本可用，其他返回 404"""
    return versioned_view(only_for_version=version)


def since(version: str):
    """自指定版本起可用"""
    return versioned_view(min_version=version)


def until(version: str):
    """指定版本之前可用"""
    return versioned_view(max_version=version, removed_in=None)
