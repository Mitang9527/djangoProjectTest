"""
功能开关（Feature Flags）。

后端优先级（从高到低）：
    1. 环境变量 ``FLAG_<NAME>``（运维热切换，无需发版）
    2. Django cache（Redis / locmem，支持运行时动态开关）
    3. settings.FEATURE_FLAGS（静态默认）

提供 ``get_flag(name)`` 查询与 ``@feature_flag(name)`` 装饰器（关闭时抛 PermissionError）。
DB 持久化模型可作为进一步增强，此处用 cache/settings/env 三件套即满足灰度需求。
"""
import os
from functools import wraps
from typing import Callable


def get_flag(name: str, *, default: bool = False) -> bool:
    env_val = os.environ.get(f"FLAG_{name.upper()}")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    try:
        from django.core.cache import cache

        cached = cache.get(f"flag:{name}")
        if cached is not None:
            return bool(cached)
    except Exception:
        pass
    try:
        from django.conf import settings

        return bool(getattr(settings, "FEATURE_FLAGS", {}).get(name, default))
    except Exception:
        return default


def feature_flag(name: str, *, default: bool = False):
    """装饰器：开关关闭时调用直接抛 PermissionError。"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not get_flag(name, default=default):
                raise PermissionError(f"feature flag '{name}' is disabled")
            return func(*args, **kwargs)

        return wrapper

    return decorator
