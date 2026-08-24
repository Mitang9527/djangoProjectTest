"""
登录防爆破：基于缓存的失败计数。

按 ``IP + 用户名`` 维度累计失败次数，超过阈值（默认 5）即锁定一段时间
（默认 900s），配合登录视图在 ``is_locked_out`` 时直接拒绝。

使用 Redis 缓存时自动跨进程共享；locmem 缓存仅单进程有效（测试/开发）。
"""
from django.conf import settings
from django.core.cache import cache


def _key(ip: str, username: str) -> str:
    return f"login_fail:{ip}:{username}"


def record_login_failure(ip: str, username: str, *, ttl: int = None) -> int:
    """记录一次失败，返回当前失败次数。"""
    ttl = ttl or getattr(settings, "LOGIN_LOCK_TTL", 900)
    key = _key(ip, username)
    fails = cache.get(key, 0) + 1
    cache.set(key, fails, ttl)
    return fails


def reset_login_failures(ip: str, username: str) -> None:
    """登录成功后清空计数。"""
    cache.delete(_key(ip, username))


def is_locked_out(ip: str, username: str) -> bool:
    """是否已达锁定阈值。"""
    threshold = getattr(settings, "LOGIN_MAX_FAILS", 5)
    return cache.get(_key(ip, username), 0) >= threshold
