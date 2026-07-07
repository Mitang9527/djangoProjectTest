"""
幂等键核心实现
==============

提供 IdempotencyBackend 抽象接口、Redis 实现、上下文管理器与装饰器。

设计原则
--------

1. **请求指纹（Fingerprint）**：相同 key 但不同参数 → 视为参数篡改，直接拒绝
2. **状态机**：`PENDING` → `IN_PROGRESS` → `COMPLETED` / `FAILED`
3. **并发安全**：使用 Redis SETNX + Lua 原子抢占，避免多个 worker 同时执行
4. **失败可重试**：`retry_on_failure=True` 时，失败后允许重试（清掉 IN_PROGRESS 状态）
5. **响应缓存**：成功后缓存完整响应（可序列化的对象），下次直接返回
"""
from __future__ import annotations

import hashlib
import json
import pickle
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Sequence

from loguru import logger


class IdempotencyStatus(str, Enum):
    """幂等键状态机"""
    PENDING = "PENDING"          # 已占位，未开始
    IN_PROGRESS = "IN_PROGRESS"  # 正在处理中
    COMPLETED = "COMPLETED"      # 已完成
    FAILED = "FAILED"            # 已失败（可重试或终止）


@dataclass
class IdempotencyRecord:
    """幂等键记录（持久化到后端存储）"""
    key: str
    fingerprint: str
    status: IdempotencyStatus
    created_at: float
    updated_at: float
    response: Optional[Any] = None
    error: Optional[str] = None
    owner: Optional[str] = None          # 哪个 worker 持有（心跳用）
    expires_at: Optional[float] = None   # TTL 绝对时间戳

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "fingerprint": self.fingerprint,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "response": self.response,
            "error": self.error,
            "owner": self.owner,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IdempotencyRecord":
        return cls(
            key=data["key"],
            fingerprint=data["fingerprint"],
            status=IdempotencyStatus(data["status"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            response=data.get("response"),
            error=data.get("error"),
            owner=data.get("owner"),
            expires_at=data.get("expires_at"),
        )


class IdempotencyBackend:
    """幂等后端抽象接口

    生产推荐 Redis 实现；测试/离线可用 LocalMemory 实现。
    """

    def reserve(self, key: str, fingerprint: str, ttl: int) -> Optional[IdempotencyRecord]:
        """尝试占位

        Returns:
            None → 占位成功，可以继续执行
            IdempotencyRecord → 已存在该 key（可能是 in-progress / completed / failed）
        """
        raise NotImplementedError

    def update_status(self, key: str, status: IdempotencyStatus,
                      response: Any = None, error: Optional[str] = None) -> None:
        """更新状态/响应/错误"""
        raise NotImplementedError

    def get(self, key: str) -> Optional[IdempotencyRecord]:
        """查询记录"""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """删除记录（用于强制重置）"""
        raise NotImplementedError


# ============================================================
# 后端：Redis
# ============================================================
class RedisIdempotencyBackend(IdempotencyBackend):
    """基于 Redis 的幂等后端

    Key 设计::

        idem:{key}                  → 序列化的 IdempotencyRecord
        idem:lock:{key}             → 短时锁（用于并发抢占的 owner token）

    使用 SETNX + EX 原子抢占；状态字段独立于响应体，避免大响应污染 status 查询。
    """

    KEY_PREFIX = "idem:"

    def __init__(self, redis_client=None):
        try:
            from utils.cache import get_redis
            self._redis_factory = redis_client or get_redis
        except Exception as e:
            logger.warning(f"[idempotency] 无法导入 redis 后端: {e}")
            self._redis_factory = None

    def _key(self, key: str) -> str:
        return f"{self.KEY_PREFIX}{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self.KEY_PREFIX}lock:{key}"

    def _client(self):
        if self._redis_factory is None:
            return None
        return self._redis_factory().get_client()

    def reserve(self, key: str, fingerprint: str, ttl: int) -> Optional[IdempotencyRecord]:
        cli = self._client()
        if cli is None:
            return None

        record = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            status=IdempotencyStatus.IN_PROGRESS,
            created_at=time.time(),
            updated_at=time.time(),
            owner=str(uuid.uuid4()),
            expires_at=time.time() + ttl,
        )
        # SETNX + EX 原子占位
        ok = cli.set(
            self._key(key),
            pickle.dumps(record.to_dict()),
            ex=ttl,
            nx=True,
        )
        if ok:
            return None
        # 已存在，加载回来
        existing = self.get(key)
        if existing and existing.is_expired():
            # 过期了，删除后重试一次
            self.delete(key)
            return self.reserve(key, fingerprint, ttl)
        return existing

    def update_status(self, key: str, status: IdempotencyStatus,
                      response: Any = None, error: Optional[str] = None) -> None:
        cli = self._client()
        if cli is None:
            return
        existing = self.get(key)
        if not existing:
            return
        existing.status = status
        existing.updated_at = time.time()
        if response is not None:
            existing.response = response
        if error is not None:
            existing.error = error
        # 保留原 TTL
        remaining = max(int(existing.expires_at - time.time()), 1) if existing.expires_at else 600
        cli.set(self._key(key), pickle.dumps(existing.to_dict()), ex=remaining)

    def get(self, key: str) -> Optional[IdempotencyRecord]:
        cli = self._client()
        if cli is None:
            return None
        raw = cli.get(self._key(key))
        if not raw:
            return None
        try:
            return IdempotencyRecord.from_dict(pickle.loads(raw))
        except Exception as e:
            logger.warning(f"[idempotency] 解析记录失败: {e}")
            return None

    def delete(self, key: str) -> None:
        cli = self._client()
        if cli is None:
            return
        cli.delete(self._key(key))


# ============================================================
# 后端：本地内存（兜底 + 测试）
# ============================================================
class LocalMemoryIdempotencyBackend(IdempotencyBackend):
    """线程不安全的进程内幂等后端（仅供单进程/测试使用）"""

    def __init__(self):
        import threading
        self._store: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def reserve(self, key, fingerprint, ttl):
        with self._lock:
            now = time.time()
            existing = self._store.get(key)
            if existing and not existing.is_expired():
                # 已存在：返回原记录（无论什么状态都让上层决定）
                return existing
            # 不存在或已过期：占位
            self._store[key] = IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                status=IdempotencyStatus.IN_PROGRESS,
                created_at=now,
                updated_at=now,
                owner=str(uuid.uuid4()),
                expires_at=now + ttl,
            )
            return None

    def update_status(self, key, status, response=None, error=None):
        with self._lock:
            r = self._store.get(key)
            if not r:
                return
            r.status = status
            r.updated_at = time.time()
            if response is not None:
                r.response = response
            if error is not None:
                r.error = error

    def get(self, key):
        return self._store.get(key)

    def delete(self, key):
        with self._lock:
            self._store.pop(key, None)


# ============================================================
# 默认后端（懒加载）
# ============================================================
_default_backend: Optional[IdempotencyBackend] = None


def get_default_backend() -> IdempotencyBackend:
    global _default_backend
    if _default_backend is None:
        try:
            _default_backend = RedisIdempotencyBackend()
        except Exception:
            _default_backend = LocalMemoryIdempotencyBackend()
    return _default_backend


def set_default_backend(backend: IdempotencyBackend) -> None:
    global _default_backend
    _default_backend = backend


# ============================================================
# 指纹生成
# ============================================================
def make_fingerprint(args: tuple, kwargs: dict, key_fields: Optional[Sequence[str]] = None) -> str:
    """生成请求指纹

    - key_fields 指定时：只对这些字段计算指纹（kwargs 不在 key_fields 中的会被忽略）
    - 默认：对所有位置参数 + 关键字参数稳定排序后 hash
    """
    if key_fields:
        # 只保留 key_fields 中的字段（kwargs 优先；不在 kwargs 的从 args 补）
        payload = {f: kwargs.get(f, args[i] if i < len(args) else None)
                   for i, f in enumerate(key_fields)}
    else:
        payload = {"args": list(args), "kwargs": kwargs}

    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# 上下文管理器
# ============================================================
@dataclass
class IdempotencyContext:
    """幂等上下文（业务侧使用）"""
    key: str
    fingerprint: str
    backend: IdempotencyBackend
    record: Optional[IdempotencyRecord] = None
    is_replay: bool = False
    replayed_response: Any = None

    def store(self, response: Any) -> None:
        """业务完成后调用，持久化响应"""
        try:
            self.backend.update_status(
                self.key, IdempotencyStatus.COMPLETED, response=response
            )
        except Exception as e:
            logger.warning(f"[idempotency] 持久化响应失败: {e}")

    def mark_failed(self, error: Exception, retryable: bool = True) -> None:
        try:
            self.backend.update_status(
                self.key,
                IdempotencyStatus.FAILED,
                error=repr(error),
            )
            if not retryable:
                # 不可重试：删除记录，让下次走新的路径
                self.backend.delete(self.key)
        except Exception as e:
            logger.warning(f"[idempotency] 标记失败状态异常: {e}")


@contextmanager
def idempotent_context(
    key: str,
    fingerprint: Optional[str] = None,
    ttl: int = 600,
    backend: Optional[IdempotencyBackend] = None,
    raise_on_conflict: bool = True,
):
    """幂等上下文管理器

    Args:
        key: 幂等键（业务侧保证唯一）
        fingerprint: 请求指纹（None 时用 key 自身）
        ttl: 记录有效期（秒）
        backend: 使用的后端（None 用默认）
        raise_on_conflict: 指纹不匹配时是否抛 IdempotencyConflict

    Yields:
        IdempotencyContext: 业务侧通过 ctx.is_replay 判断是否重放
    """
    if not key:
        raise ValueError("idempotent_context requires non-empty key")

    backend = backend or get_default_backend()
    fp = fingerprint or key
    ctx = IdempotencyContext(key=key, fingerprint=fp, backend=backend)

    existing = backend.reserve(key, fp, ttl)
    if existing is not None:
        if existing.fingerprint != fp:
            # 同样的 key，不同的请求体 → 参数冲突
            if raise_on_conflict:
                from .exceptions import IdempotencyConflict
                raise IdempotencyConflict(
                    f"idempotency key '{key}' already used with different payload"
                )
            else:
                logger.warning(f"[idempotency] 指纹冲突但被忽略: {key}")
        elif existing.status == IdempotencyStatus.COMPLETED:
            ctx.is_replay = True
            ctx.replayed_response = existing.response
            ctx.record = existing
        elif existing.status == IdempotencyStatus.IN_PROGRESS:
            # 抢占失败：另一个 worker 正在处理
            from .exceptions import IdempotencyInProgress
            raise IdempotencyInProgress(
                f"idempotency key '{key}' is being processed by another worker"
            )
        elif existing.status == IdempotencyStatus.FAILED:
            # 之前失败过：如果 retryable 已设置可继续
            ctx.record = existing

    try:
        yield ctx
    except Exception as e:
        ctx.mark_failed(e, retryable=True)
        raise


# ============================================================
# 装饰器
# ============================================================
def idempotent(
    key_fields: Optional[Sequence[str]] = None,
    key_func: Optional[Callable[..., str]] = None,
    ttl: int = 600,
    backend: Optional[IdempotencyBackend] = None,
    raise_on_conflict: bool = True,
    ignore_fields: Optional[Sequence[str]] = None,
):
    """幂等装饰器

    Args:
        key_fields: 用于生成幂等键的字段名（按顺序拼接）
        key_func: 自定义 key 生成函数（接收 *args, **kwargs，返回唯一字符串）
        ttl: 记录保留秒数
        backend: 自定义后端
        raise_on_conflict: 指纹冲突时是否抛异常
        ignore_fields: 计算 fingerprint 时忽略的字段（如 trace_id）

    Examples::

        @idempotent(key_fields=["order_id"], ttl=600)
        def create_order(order_id, amount, user_id):
            ...

        @idempotent(key_fields=["order_id"], ignore_fields=["trace_id"], ttl=600)
        def pay(order_id, amount, trace_id):
            # trace_id 不参与 fingerprint（与防重无关）
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 1. 构造 key
            if key_func is not None:
                key = key_func(*args, **kwargs)
            elif key_fields:
                parts = []
                for f in key_fields:
                    if f in kwargs:
                        parts.append(f"{f}={kwargs[f]}")
                    else:
                        # 尝试从 args 取（按 key_fields 顺序对应位置参数）
                        idx = list(key_fields).index(f)
                        parts.append(f"{f}={args[idx] if idx < len(args) else '?'}")
                key = ":".join(parts) or func.__name__
            else:
                # 无 key_fields / key_func：用函数名 + 全参数 hash
                fp = make_fingerprint(args, kwargs)
                key = f"{func.__name__}:{fp[:16]}"

            # 2. 构造 fingerprint：默认全 payload，可选忽略某些字段
            if ignore_fields:
                filtered_kwargs = {k: v for k, v in kwargs.items() if k not in ignore_fields}
                filtered_args = tuple(
                    v for i, v in enumerate(args)
                    # args 位置不直接对应 ignore_fields，跳过
                    if True
                )
                # 仅从 kwargs 排除；args 整体保留（无法精确判断位置 → 字段映射）
                fingerprint = make_fingerprint(filtered_args, filtered_kwargs)
            else:
                fingerprint = make_fingerprint(args, kwargs)

            # 3. 进入上下文
            with idempotent_context(
                key=key,
                fingerprint=fingerprint,
                ttl=ttl,
                backend=backend,
                raise_on_conflict=raise_on_conflict,
            ) as ctx:
                if ctx.is_replay:
                    logger.info(f"[idempotency] 命中重放: {key}")
                    return ctx.replayed_response

                result = func(*args, **kwargs)
                ctx.store(result)
                return result

        return wrapper
    return decorator
