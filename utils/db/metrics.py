"""
DB 连接池 - 监控指标
=====================

每个池独立的轻量计数器：
  acquired        借出次数
  created         新建连接次数
  discarded       丢弃连接次数
  wait            触发等待次数
  timeout         超时次数
  error           错误次数（按类型分桶）
  hits / misses   命中（复用）/ 未命中（新建）

使用：
  from utils.db import get_metrics
  m = get_metrics("default")
  m.inc_acquired()
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict


class PoolMetrics:
    """单池指标收集器（线程安全）"""

    __slots__ = (
        "name", "lock", "_start_at",
        "acquired", "created", "discarded",
        "wait_count", "timeout_count", "error_count",
        "hits", "misses",
    )

    def __init__(self, name: str):
        self.name = name
        self.lock = threading.Lock()
        self._start_at = time.time()
        self.acquired = 0
        self.created = 0
        self.discarded = 0
        self.wait_count = 0
        self.timeout_count = 0
        self.error_count = 0
        self.hits = 0
        self.misses = 0

    # ── 写入 ────────────────────────────────────────
    def inc_acquired(self):
        with self.lock:
            self.acquired += 1

    def inc_created(self):
        with self.lock:
            self.created += 1
            self.misses += 1

    def inc_hit(self):
        with self.lock:
            self.hits += 1

    def inc_discarded(self):
        with self.lock:
            self.discarded += 1

    def inc_wait(self):
        with self.lock:
            self.wait_count += 1

    def inc_timeout(self):
        with self.lock:
            self.timeout_count += 1

    def inc_error(self, kind: str = "generic"):
        with self.lock:
            self.error_count += 1

    # ── 读出 ────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total) if total > 0 else 0.0
            return {
                "acquired": self.acquired,
                "created": self.created,
                "discarded": self.discarded,
                "wait_count": self.wait_count,
                "timeout_count": self.timeout_count,
                "error_count": self.error_count,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(hit_rate, 4),
                "uptime_seconds": int(time.time() - self._start_at),
            }

    def reset(self):
        with self.lock:
            self._start_at = time.time()
            self.acquired = self.created = self.discarded = 0
            self.wait_count = self.timeout_count = self.error_count = 0
            self.hits = self.misses = 0


# ─────────────────────────────────────────────────────────────
# 全局注册表
# ─────────────────────────────────────────────────────────────
_metrics_registry: Dict[str, PoolMetrics] = {}
_global_lock = threading.Lock()


def get_metrics(name: str) -> PoolMetrics:
    """获取或创建指定池名的指标对象"""
    with _global_lock:
        m = _metrics_registry.get(name)
        if m is None:
            m = PoolMetrics(name)
            _metrics_registry[name] = m
        return m


def all_metrics() -> Dict[str, Dict[str, Any]]:
    """获取所有池的指标快照"""
    with _global_lock:
        return {name: m.snapshot() for name, m in _metrics_registry.items()}


def reset_all_metrics():
    with _global_lock:
        for m in _metrics_registry.values():
            m.reset()
