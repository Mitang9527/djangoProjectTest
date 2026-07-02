"""
缓存管理器
- 缓存键生成（版本控制）
- 标签化失效
- SCAN 替代 KEYS 批量删除
- 缓存预热
- 命中率统计
"""
import time
import hashlib
import functools
from typing import Optional, Callable, Any, Dict, List, Set
from django.conf import settings
from django.core.cache import cache
from loguru import logger

# =====================================================
# 缓存版本号（变更后旧缓存自动失效）
# =====================================================
CACHE_VERSION = "v3"

# =====================================================
# 缓存标签表（Redis Hash: cache_tags）
# =====================================================
TAG_KEY = f"cache_tags:{CACHE_VERSION}"


def make_cache_key(key, key_prefix, version):
    """Django CACHES KEY_FUNCTION 兼容签名"""
    return f"{CACHE_VERSION}:{key_prefix}:{key}"


def _build_key(prefix: str, *parts: str) -> str:
    """构建版本化缓存键"""
    raw = ":".join(parts)
    return f"{CACHE_VERSION}:{prefix}:{raw}"


def _build_tag_pattern(tag: str) -> str:
    """构建标签的键模式"""
    return f"{CACHE_VERSION}:tag:{tag}:*"


# =====================================================
# 基础操作（带版本控制）
# =====================================================

def cache_get(prefix: str, *parts: str, default=None) -> Any:
    """获取缓存（版本化）"""
    key = _build_key(prefix, *parts)
    return cache.get(key, default)


def cache_set(value: Any, prefix: str, *parts: str, timeout: int = None, tags: List[str] = None):
    """
    写入缓存（支持标签）

    Args:
        value: 缓存值
        prefix: 键前缀（如 'dashboard', 'user_perms'）
        *parts: 键后缀部分
        timeout: 过期时间（秒），默认使用 CACHES TIMEOUT
        tags: 标签列表，用于批量失效
    """
    key = _build_key(prefix, *parts)
    cache.set(key, value, timeout=timeout)

    # 记录标签 → 键的映射
    if tags:
        _add_tag_mapping(tags, key)


def cache_delete(prefix: str, *parts: str):
    """删除单个缓存键"""
    key = _build_key(prefix, *parts)
    cache.delete(key)


# =====================================================
# 标签化失效
# =====================================================

def _add_tag_mapping(tags: List[str], cache_key: str):
    """记录标签到缓存键的映射（存入缓存自身）"""
    for tag in tags:
        try:
            tag_key = _build_tag_pattern(tag)
            existing = cache.get(tag_key) or []
            if cache_key not in existing:
                existing.append(cache_key)
                cache.set(tag_key, existing, timeout=60 * 60 * 24 * 30)  # 标签映射 30 天
        except Exception as e:
            logger.warning(f"[Cache] 标签映射写入失败 tag={tag}: {e}")


def invalidate_by_tag(tag: str) -> int:
    """
    按标签批量失效缓存

    Args:
        tag: 标签名（如 'tenant', 'user_perms', 'dashboard'）

    Returns:
        删除的键数量
    """
    deleted = 0
    try:
        tag_key = _build_tag_pattern(tag)
        tagged_keys = cache.get(tag_key) or []
        for key in tagged_keys:
            cache.delete(key)
            deleted += 1
        # 清理标签映射
        cache.delete(tag_key)
        logger.info(f"[Cache] 标签失效 tag={tag}, 删除 {deleted} 个键")
    except Exception as e:
        logger.error(f"[Cache] 标签失效失败 tag={tag}: {e}")
    return deleted


def invalidate_by_pattern(prefix: str, pattern: str = "*") -> int:
    """
    按模式批量失效（使用 SCAN，生产安全）

    Args:
        prefix: 缓存前缀
        pattern: 匹配模式

    Returns:
        删除的键数量
    """
    try:
        # 尝试 Redis 的 SCAN 方式（生产安全）
        from django_redis import get_redis_connection
        client = get_redis_connection("default")
        full_pattern = f"{CACHE_VERSION}:{prefix}:{pattern}"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=full_pattern, count=100)
            if keys:
                client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        if deleted:
            logger.info(f"[Cache] 模式失效 pattern={full_pattern}, 删除 {deleted} 个键")
        return deleted
    except ImportError:
        # django-redis 不可用，回退到 Django cache API
        import re
        from django.core.cache import caches
        c = caches['default']
        if hasattr(c, '_cache') and hasattr(c._cache, 'get_client'):
            client = c._cache.get_client()
            try:
                full_pattern = f"{CACHE_VERSION}:{prefix}:{pattern}"
                deleted = 0
                cursor = 0
                while True:
                    cursor, keys = client.scan(cursor, match=full_pattern, count=100)
                    if keys:
                        client.delete(*keys)
                        deleted += len(keys)
                    if cursor == 0:
                        break
                return deleted
            except Exception as e:
                logger.warning(f"[Cache] SCAN 删除失败，回退到 delete_pattern: {e}")
        # 最后兜底
        regex_pattern = f"^{CACHE_VERSION}:{prefix}:{pattern.replace('*', '.*')}$"
        if hasattr(c, 'delete_pattern'):
            c.delete_pattern(regex_pattern)
            return 1


# =====================================================
# 缓存装饰器
# =====================================================

def cached(prefix: str, ttl: int = 300, tags: List[str] = None,
           key_func: Optional[Callable] = None):
    """
    Django Cache 缓存装饰器（版本化 + 标签支持）

    Args:
        prefix: 键前缀
        ttl: 过期时间（秒），默认 5 分钟
        tags: 标签列表
        key_func: 自定义键生成函数
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if key_func:
                key_parts = [key_func(*args, **kwargs)]
            else:
                sorted_kwargs = sorted(kwargs.items())
                key_parts = [str(args), str(sorted_kwargs)]
                key_parts = [hashlib.md5(p.encode()).hexdigest()[:16] for p in key_parts]

            cached_value = cache_get(prefix, *key_parts)
            if cached_value is not None:
                return cached_value

            result = func(*args, **kwargs)
            cache_set(result, prefix, *key_parts, timeout=ttl, tags=tags)
            return result
        return wrapper
    return decorator


# =====================================================
# 缓存预热
# =====================================================

WARMUP_REGISTRY: Dict[str, Callable[[], Any]] = {}


def register_warmup(name: str):
    """装饰器：注册缓存预热函数"""
    def decorator(func: Callable) -> Callable:
        WARMUP_REGISTRY[name] = func
        return func
    return decorator


def warmup_all(verbose: bool = True) -> Dict[str, bool]:
    """
    执行所有已注册的预热函数

    Returns:
        {函数名: 是否成功}
    """
    results = {}
    for name, func in WARMUP_REGISTRY.items():
        try:
            func()
            results[name] = True
            if verbose:
                logger.info(f"[Cache] 预热成功: {name}")
        except Exception as e:
            results[name] = False
            logger.error(f"[Cache] 预热失败 {name}: {e}")
    return results


# =====================================================
# 命中率统计
# =====================================================

class CacheStats:
    """内存级缓存命中率统计（非持久化，供监控面板用）"""

    _hits: int = 0
    _misses: int = 0
    _sets: int = 0
    _invalidations: int = 0

    @classmethod
    def record_hit(cls):
        cls._hits += 1

    @classmethod
    def record_miss(cls):
        cls._misses += 1

    @classmethod
    def record_set(cls):
        cls._sets += 1

    @classmethod
    def record_invalidation(cls, count: int = 1):
        cls._invalidations += count

    @classmethod
    def snapshot(cls) -> dict:
        total = cls._hits + cls._misses
        hit_rate = round(cls._hits / total * 100, 1) if total > 0 else 0
        return {
            "hits": cls._hits,
            "misses": cls._misses,
            "sets": cls._sets,
            "invalidations": cls._invalidations,
            "total_requests": total,
            "hit_rate": hit_rate,
        }

    @classmethod
    def reset(cls):
        cls._hits = 0
        cls._misses = 0
        cls._sets = 0
        cls._invalidations = 0


# =====================================================
# 兼容旧接口
# =====================================================

def clear_redis_cache(key_pattern: str) -> int:
    """
    清除指定模式的缓存（SCAN 方式，生产安全）

    Args:
        key_pattern: 键模式（如 "cache:*"）
    """
    try:
        # 先用 SCAN 方式
        from django_redis import get_redis_connection
        client = get_redis_connection("default")
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=key_pattern, count=100)
            if keys:
                client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        if deleted:
            logger.info(f"[Cache] 已清除 {deleted} 个键: {key_pattern}")
        return deleted
    except Exception as e:
        # 回退到旧方式
        try:
            from utils.cache.redis_client import get_redis
            client = get_redis()
            keys = client.keys(key_pattern)
            if keys:
                deleted = client.delete(*keys)
                logger.info(f"[Cache] 已清除 {deleted} 个键: {key_pattern}")
                return deleted
        except Exception as e2:
            logger.error(f"[Cache] 清除缓存失败: {e2}")
        return 0
