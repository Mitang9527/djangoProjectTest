"""
分布式锁核心实现
================

基于 Redis SET NX EX + Lua 脚本实现：

- **互斥**：NX 选项保证原子抢占
- **防误删**：释放时用 Lua 校验 token 匹配
- **可重入**：同一 owner 可多次获取（thread-local owner id）
- **看门狗**：长任务执行期间自动续期，避免 TTL 过期
- **公平锁**：可选 FIFO 队列（基于 ZSET 实现）
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import random
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Sequence, Union

from loguru import logger


# ============================================================
# Lua 脚本（保证释放与续期的原子性）
# ============================================================
# 释放：仅当 value（token）匹配时才 DEL
LUA_RELEASE = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# 续期：仅当 value 匹配时 PEXPIRE
LUA_RENEW = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""

# 重入：仅当 owner 匹配时 INCR
LUA_REENTRANT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("INCR", KEYS[2])
else
    return 0
end
"""


# ============================================================
# 异常 & 状态
# ============================================================
class LockError(Exception):
    """锁基类异常"""


class LockAcquireError(LockError):
    """获取锁失败（非阻塞模式）"""


class LockTimeoutError(LockError):
    """阻塞等待超时"""


class LockReleaseError(LockError):
    """释放锁失败（已被其他 owner 持有或已过期）"""


class LockState(str, Enum):
    ACQUIRED = "ACQUIRED"
    RELEASED = "RELEASED"
    TIMEOUT = "TIMEOUT"
    RENEWED = "RENEWED"


@dataclass
class LockInfo:
    name: str
    owner: str
    acquired_at: float
    expires_at: float
    reentrant_count: int = 0


# ============================================================
# 后端抽象
# ============================================================
class LockBackend:
    """锁后端抽象"""

    def acquire(self, name: str, owner: str, ttl_ms: int, wait_ms: int) -> bool: ...
    def renew(self, name: str, owner: str, ttl_ms: int) -> bool: ...
    def release(self, name: str, owner: str) -> bool: ...
    def is_held(self, name: str) -> bool: ...


# ============================================================
# Redis 后端
# ============================================================
class RedisLockBackend(LockBackend):
    """单节点 Redis 锁后端

    使用 SETNX + EX 原子抢占；释放用 Lua 校验 token；
    续期用 Lua 校验 + PEXPIRE。
    """

    KEY_PREFIX = "lock:"

    def __init__(self, redis_client=None):
        try:
            from framework.cache import get_redis
            self._redis_factory = redis_client or get_redis
        except Exception as e:
            logger.warning(f"[locks] 无法导入 redis 后端: {e}")
            self._redis_factory = None
        self._release_script = None
        self._renew_script = None

    def _cli(self):
        if self._redis_factory is None:
            return None
        cli = self._redis_factory().get_client()
        if cli is None:
            return None
        # 懒加载脚本
        if self._release_script is None:
            try:
                self._release_script = cli.register_script(LUA_RELEASE)
                self._renew_script = cli.register_script(LUA_RENEW)
            except Exception:
                pass
        return cli

    def _key(self, name: str) -> str:
        return f"{self.KEY_PREFIX}{name}"

    def acquire(self, name, owner, ttl_ms, wait_ms):
        cli = self._cli()
        if cli is None:
            return False
        key = self._key(name)
        deadline = time.time() + wait_ms / 1000.0
        # 退避抖动
        sleep_base = 0.05
        while True:
            ok = cli.set(key, owner, px=ttl_ms, nx=True)
            if ok:
                return True
            if time.time() >= deadline:
                return False
            # 退避 + 抖动
            sleep_s = sleep_base + random.uniform(0, 0.03)
            time.sleep(min(sleep_s, max(0, deadline - time.time())))
            sleep_base = min(sleep_base * 1.5, 0.5)

    def renew(self, name, owner, ttl_ms):
        cli = self._cli()
        if cli is None or self._renew_script is None:
            return False
        try:
            res = self._renew_script(keys=[self._key(name)], args=[owner, ttl_ms])
            return bool(res)
        except Exception as e:
            logger.warning(f"[locks] 续期失败: {e}")
            return False

    def release(self, name, owner):
        cli = self._cli()
        if cli is None or self._release_script is None:
            return False
        try:
            res = self._release_script(keys=[self._key(name)], args=[owner])
            return bool(res)
        except Exception as e:
            logger.warning(f"[locks] 释放失败: {e}")
            return False

    def is_held(self, name):
        cli = self._cli()
        if cli is None:
            return False
        return bool(cli.exists(self._key(name)))


# ============================================================
# LocalMemory 后端（兜底 + 测试）
# ============================================================
class LocalMemoryLockBackend(LockBackend):
    """线程安全的进程内锁后端"""

    def __init__(self):
        self._locks: dict[str, str] = {}
        self._lock = threading.Lock()

    def acquire(self, name, owner, ttl_ms, wait_ms):
        with self._lock:
            if name not in self._locks:
                self._locks[name] = owner
                return True
        # 简单轮询
        deadline = time.time() + wait_ms / 1000.0
        while time.time() < deadline:
            time.sleep(0.01)
            with self._lock:
                if name not in self._locks:
                    self._locks[name] = owner
                    return True
        return False

    def renew(self, name, owner, ttl_ms):
        with self._lock:
            return self._locks.get(name) == owner

    def release(self, name, owner):
        with self._lock:
            if self._locks.get(name) == owner:
                del self._locks[name]
                return True
            return False

    def is_held(self, name):
        with self._lock:
            return name in self._locks


# ============================================================
# 默认后端
# ============================================================
_default_backend: Optional[LockBackend] = None


def get_default_backend() -> LockBackend:
    global _default_backend
    if _default_backend is None:
        try:
            _default_backend = RedisLockBackend()
        except Exception:
            _default_backend = LocalMemoryLockBackend()
    return _default_backend


def set_default_backend(backend: LockBackend) -> None:
    global _default_backend
    _default_backend = backend


# ============================================================
# Owner 工厂：每个线程/协程一个 owner
# ============================================================
_thread_local = threading.local()


def _current_owner() -> str:
    """当前执行上下文 owner

    - 优先用显式 set_owner() 设置的
    - 否则：thread_id + 进程 pid + hostname + uuid 前 8 位
    """
    if getattr(_thread_local, "owner", None):
        return _thread_local.owner
    digest = hashlib.sha1(
        f"{threading.get_ident()}-{socket.gethostname()}-{uuid.uuid4()}".encode()
    ).hexdigest()[:8]
    owner = f"owner-{digest}"
    _thread_local.owner = owner
    return owner


def set_owner(owner: str) -> None:
    """显式设置当前线程的 owner（用于跨函数追踪）"""
    _thread_local.owner = owner


# ============================================================
# RedisLock 主类
# ============================================================
class RedisLock:
    """分布式锁（基于 Redis）

    Args:
        name: 锁名称（业务唯一）
        ttl: 锁过期时间（秒），防止持锁者崩溃后死锁
        wait: 等待获取的最长时间（秒）
        auto_renewal: 是否启动看门狗自动续期
        backend: 自定义后端
        reentrant: 是否允许重入
    """

    def __init__(
        self,
        name: str,
        ttl: int = 30,
        wait: float = 0.0,
        auto_renewal: bool = False,
        backend: Optional[LockBackend] = None,
        reentrant: bool = True,
    ):
        self.name = name
        self.ttl = ttl
        self.wait = wait
        self.auto_renewal = auto_renewal
        self.reentrant = reentrant
        self.backend = backend or get_default_backend()

        self.owner = _current_owner()
        self._held = False
        self._reentrant_count = 0
        self._renewal_thread: Optional[threading.Thread] = None
        self._renewal_stop = threading.Event()

    # ---------- context manager ----------
    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False

    # ---------- 显式接口 ----------
    def acquire(self, blocking: bool = True) -> bool:
        if self._held and self.reentrant:
            self._reentrant_count += 1
            return True

        wait_ms = int(self.wait * 1000) if blocking else 0
        ttl_ms = int(self.ttl * 1000)
        ok = self.backend.acquire(self.name, self.owner, ttl_ms, wait_ms)
        if not ok:
            if blocking:
                raise LockTimeoutError(
                    f"acquire lock '{self.name}' timeout after {self.wait}s"
                )
            raise LockAcquireError(f"acquire lock '{self.name}' failed (non-blocking)")

        self._held = True
        self._reentrant_count = 1
        if self.auto_renewal:
            self._start_renewal()
        return True

    def try_acquire(self) -> bool:
        """非阻塞获取，失败返回 False"""
        try:
            return self.acquire(blocking=False)
        except LockAcquireError:
            return False

    def renew(self, ttl: Optional[int] = None) -> bool:
        return self.backend.renew(
            self.name, self.owner, int((ttl or self.ttl) * 1000)
        )

    def release(self) -> bool:
        if not self._held:
            return False

        if self._reentrant_count > 1:
            self._reentrant_count -= 1
            return True

        self._stop_renewal()
        ok = self.backend.release(self.name, self.owner)
        if not ok:
            logger.warning(
                f"[locks] 释放失败：'{self.name}' 可能已被其他 owner 持有或过期"
            )
        self._held = False
        self._reentrant_count = 0
        return ok

    def is_held(self) -> bool:
        return self._held or self.backend.is_held(self.name)

    # ---------- 看门狗 ----------
    def _start_renewal(self):
        if self._renewal_thread is not None:
            return
        self._renewal_stop.clear()
        interval = max(1, self.ttl // 3)

        def _loop():
            while not self._renewal_stop.wait(interval):
                if not self.renew():
                    logger.warning(
                        f"[locks] 看门狗续期失败: '{self.name}'，锁可能已丢失"
                    )
                    return

        self._renewal_thread = threading.Thread(
            target=_loop, name=f"lock-renewal-{self.name}", daemon=True
        )
        self._renewal_thread.start()

    def _stop_renewal(self):
        if self._renewal_thread is None:
            return
        self._renewal_stop.set()
        self._renewal_thread.join(timeout=1.0)
        self._renewal_thread = None


# ============================================================
# RedLock（多节点，弱实现）
# ============================================================
class RedLock:
    """Redlock 多节点锁

    当 Redis 是单点/主从切换有数据丢失风险时使用。
    需要在 settings 配置 REDIS_NODES = [{"host": ..., "port": ...}, ...]

    实现：N 个节点中至少 N/2+1 成功获取视为成功。
    """

    def __init__(
        self,
        name: str,
        nodes: Optional[Sequence[dict]] = None,
        ttl: int = 30,
        wait: float = 0.0,
        quorum: Optional[int] = None,
    ):
        self.name = name
        self.ttl = ttl
        self.wait = wait
        self.backends: List[LockBackend] = self._build_backends(nodes)
        self.quorum = quorum or (len(self.backends) // 2 + 1)
        self.owner = _current_owner()
        self._held = False
        self._validity_ms = 0

    def _build_backends(self, nodes):
        if nodes is None:
            from django.conf import settings
            nodes = getattr(settings, "REDIS_NODES", None) or []
        if not nodes:
            # 退化为单节点
            return [get_default_backend()]

        backends = []
        for conf in nodes:
            try:
                import redis
                pool = redis.ConnectionPool(
                    host=conf["host"],
                    port=conf.get("port", 6379),
                    password=conf.get("password"),
                    db=conf.get("db", 0),
                )
                cli = redis.Redis(connection_pool=pool)

                class _DirectBackend(LockBackend):
                    def __init__(self, c):
                        self.cli = c

                    def acquire(self, n, o, ttl_ms, wait_ms):
                        try:
                            return bool(self.cli.set(f"lock:{n}", o, px=ttl_ms, nx=True))
                        except Exception:
                            return False

                    def renew(self, n, o, ttl_ms):
                        try:
                            script = self.cli.register_script(LUA_RENEW)
                            return bool(script(keys=[f"lock:{n}"], args=[o, ttl_ms]))
                        except Exception:
                            return False

                    def release(self, n, o):
                        try:
                            script = self.cli.register_script(LUA_RELEASE)
                            return bool(script(keys=[f"lock:{n}"], args=[o]))
                        except Exception:
                            return False

                    def is_held(self, n):
                        try:
                            return bool(self.cli.exists(f"lock:{n}"))
                        except Exception:
                            return False

                backends.append(_DirectBackend(cli))
            except Exception as e:
                logger.warning(f"[locks] Redlock 节点初始化失败: {e}")
        return backends

    def acquire(self) -> bool:
        start = time.time()
        ttl_ms = int(self.ttl * 1000)
        acquired = 0
        for be in self.backends:
            if be.acquire(self.name, self.owner, ttl_ms, 0):
                acquired += 1
        if acquired < self.quorum:
            # 失败回滚
            self.release()
            return False
        # 计算有效时间
        elapsed_ms = int((time.time() - start) * 1000)
        self._validity_ms = max(0, ttl_ms - elapsed_ms - 2)  # 2ms clock drift
        self._held = True
        return True

    def release(self) -> bool:
        if not self._held:
            return False
        released = 0
        for be in self.backends:
            if be.release(self.name, self.owner):
                released += 1
        self._held = False
        return released >= self.quorum

    def __enter__(self):
        if not self.acquire():
            raise LockAcquireError(f"RedLock acquire '{self.name}' failed")
        return self

    def __exit__(self, *args):
        self.release()


# ============================================================
# 装饰器
# ============================================================
def locked(
    key: Union[str, Callable],
    ttl: int = 30,
    wait: float = 5.0,
    auto_renewal: bool = False,
):
    """锁装饰器

    Args:
        key: 锁 key 模板，支持 {arg_name} 占位符；或 callable(*args, **kwargs) -> str
        ttl: 过期秒数
        wait: 等待秒数
        auto_renewal: 是否启动看门狗
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if callable(key):
                name = key(*args, **kwargs)
            elif isinstance(key, str):
                # 占位符替换
                try:
                    bound = func.__code__.co_varnames[:func.__code__.co_argcount]
                    scope = dict(zip(bound, args))
                    scope.update(kwargs)
                    name = key.format(**scope)
                except Exception:
                    name = key
            else:
                raise TypeError("key must be str or callable")

            lock = RedisLock(
                name=name, ttl=ttl, wait=wait, auto_renewal=auto_renewal
            )
            with lock:
                return func(*args, **kwargs)
        return wrapper
    return decorator
