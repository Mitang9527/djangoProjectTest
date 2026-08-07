"""
缓存工具包
包含 Redis、缓存管理、预热、失效等功能
"""
from .redis_client import get_redis, RedisClient, get_cache
from .cache_manager import (
    CACHE_VERSION,
    cache_get,
    cache_set,
    cache_delete,
    invalidate_by_tag,
    invalidate_by_pattern,
    cached,
    warmup_all,
    register_warmup,
    CacheStats,
    clear_redis_cache,
)

__all__ = [
    # Redis 客户端
    'get_redis', 'RedisClient', 'get_cache',
    # 缓存管理器
    'CACHE_VERSION',
    'cache_get', 'cache_set', 'cache_delete',
    'invalidate_by_tag', 'invalidate_by_pattern',
    'cached', 'warmup_all', 'register_warmup',
    'CacheStats', 'clear_redis_cache',
]

# 自动注册缓存预热任务
from . import warmup_tasks  # noqa: E402, F401
