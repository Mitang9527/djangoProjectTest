"""
共享状态存储
============

熔断器、隔离舱的状态需要跨进程/跨 worker 共享（生产环境），
抽象为 StateStore 接口。默认 InMemoryStateStore 仅单进程有效。

生产推荐 RedisStateStore（已在文件内实现）。"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from loguru import logger


class StateStore:
    """状态存储抽象"""

    def get(self, key: str) -> Optional[Any]: ...
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def incr(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int: ...
    def expire(self, key: str, ttl: int) -> None: ...


class InMemoryStateStore(StateStore):
    """进程内状态存储"""

    def __init__(self):
        self._data: dict[str, tuple[Any, Optional[float]]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            v = self._data.get(key)
            if not v:
                return None
            value, expire_at = v
            if expire_at and time.time() > expire_at:
                del self._data[key]
                return None
            return value

    def set(self, key, value, ttl=None):
        with self._lock:
            expire_at = time.time() + ttl if ttl else None
            self._data[key] = (value, expire_at)

    def delete(self, key):
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key, amount=1, ttl=None):
        with self._lock:
            v = self._data.get(key)
            if v is None or (v[1] and time.time() > v[1]):
                new_value = amount
                expire_at = time.time() + ttl if ttl else None
            else:
                try:
                    new_value = int(v[0]) + amount
                except Exception:
                    new_value = amount
                expire_at = v[1] if ttl is None else time.time() + ttl
            self._data[key] = (new_value, expire_at)
            return new_value

    def expire(self, key, ttl):
        with self._lock:
            v = self._data.get(key)
            if v:
                self._data[key] = (v[0], time.time() + ttl)


class RedisStateStore(StateStore):
    """Redis 状态存储（生产推荐）"""

    KEY_PREFIX = "reliability:"

    def __init__(self, redis_client=None):
        try:
            from framework.cache import get_redis
            self._factory = redis_client or get_redis
        except Exception as e:
            logger.warning(f"[reliability] Redis 状态存储初始化失败: {e}")
            self._factory = None

    def _cli(self):
        if self._factory is None:
            return None
        return self._factory().get_client()

    def _key(self, k):
        return f"{self.KEY_PREFIX}{k}"

    def get(self, key):
        cli = self._cli()
        if cli is None:
            return None
        try:
            raw = cli.get(self._key(key))
            if raw is None:
                return None
            try:
                import pickle
                return pickle.loads(raw)
            except Exception:
                return raw.decode() if isinstance(raw, bytes) else raw
        except Exception:
            return None

    def set(self, key, value, ttl=None):
        cli = self._cli()
        if cli is None:
            return
        import pickle
        try:
            cli.set(self._key(key), pickle.dumps(value), ex=ttl)
        except Exception:
            pass

    def delete(self, key):
        cli = self._cli()
        if cli is None:
            return
        try:
            cli.delete(self._key(key))
        except Exception:
            pass

    def incr(self, key, amount=1, ttl=None):
        cli = self._cli()
        if cli is None:
            return 0
        try:
            v = cli.incr(self._key(key), amount)
            if ttl:
                cli.expire(self._key(key), ttl)
            return int(v)
        except Exception:
            return 0

    def expire(self, key, ttl):
        cli = self._cli()
        if cli is None:
            return
        try:
            cli.expire(self._key(key), ttl)
        except Exception:
            pass


# ============================================================
# 默认状态存储
# ============================================================
_default_store: Optional[StateStore] = None


def get_state_store() -> StateStore:
    global _default_store
    if _default_store is None:
        try:
            _default_store = RedisStateStore()
        except Exception:
            _default_store = InMemoryStateStore()
    return _default_store


def set_state_store(store: StateStore) -> None:
    global _default_store
    _default_store = store
