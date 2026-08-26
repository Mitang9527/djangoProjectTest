"""
ERROR 日志突增监控（loguru sink 计数 + 阈值）
============================================

通过向 loguru 注册一个 ERROR+ 级别的 sink，按滑动时间窗口统计 ERROR/CRITICAL
日志条数。一个 Celery Beat 任务 (`core.tasks.check_error_spike`) 周期性读取窗口
计数，超过阈值则经 alert_system 触发告警（含冷却，避免刷屏）。

用法:
    模块导入时即挂载单例监控器，sink 由 LogManager._setup() 注册:
        from framework.log_utils.error_spike import error_spike_monitor
        n = error_spike_monitor.count_in_window()   # 当前窗口内 ERROR 条数

    若要手动安装（不依赖 LogManager），可调用:
        from framework.log_utils.error_spike import install_error_spike_sink
        install_error_spike_sink()
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import List, Tuple


class ErrorSpikeMonitor:
    """
    ERROR 日志滑动窗口计数器（线程安全）。

    内部按 bucket_seconds 分桶存储时间戳计数，仅保留 window_seconds 内的桶，
    因此内存占用恒定。另维护一个跨窗口的 total 计数（供 beat 任务重置后统计）。
    """

    def __init__(self, window_seconds: int = 300, bucket_seconds: int = 60):
        self.window_seconds = window_seconds
        self.bucket_seconds = max(1, bucket_seconds)
        self._lock = threading.Lock()
        # 每个元素为 [bucket_start_ts, count]
        self._buckets: deque = deque()
        self._total = 0

    # ── 写入 ────────────────────────────────────────
    def record(self, n: int = 1) -> None:
        if n <= 0:
            return
        now = time.time()
        bucket_start = int(now // self.bucket_seconds) * self.bucket_seconds
        with self._lock:
            if self._buckets and self._buckets[-1][0] == bucket_start:
                self._buckets[-1][1] += n
            else:
                self._prune_locked(now)
                self._buckets.append([bucket_start, n])
            self._total += n

    # ── 读取 ────────────────────────────────────────
    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._buckets and self._buckets[0][0] < cutoff:
            self._buckets.popleft()

    def count_in_window(self) -> int:
        """窗口内 ERROR 条数（仅统计 window_seconds 内的分桶）。"""
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            return sum(b[1] for b in self._buckets)

    def buckets(self) -> List[Tuple[int, int]]:
        """返回当前窗口内的分桶快照 [(bucket_start, count), ...]"""
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            return list(self._buckets)

    def total(self) -> int:
        with self._lock:
            return self._total

    def reset_total(self) -> int:
        with self._lock:
            old = self._total
            self._total = 0
            return old

    def is_spiking(self, threshold: int) -> bool:
        return self.count_in_window() >= threshold


# 全局单例（默认 5 分钟窗口，1 分钟分桶）
error_spike_monitor = ErrorSpikeMonitor()


def _error_spike_sink(message) -> None:
    """
    loguru sink — 仅统计 ERROR+ 级别。

    放在 loguru_control.LogManager._setup() 中注册；若手动安装也可调用
    install_error_spike_sink()。sink 异常不应外抛。
    """
    try:
        record = message.record
        # ERROR 级别数字（loguru 中 ERROR=40）
        if record["level"].no >= 40:
            error_spike_monitor.record(1)
            # 同步累计 Prometheus 指标（延迟导入，避免循环依赖）
            try:
                from framework.metrics import record_error_log
                source = record["extra"].get("source", "app")
                record_error_log(source=source)
            except Exception:
                pass
    except Exception:
        pass


def install_error_spike_sink() -> int:
    """手动把计数 sink 挂到全局 logger（返回 sink id；已挂过则幂等）。"""
    from loguru import logger

    sink_id = logger.add(_error_spike_sink, level="ERROR", format=_make_file_format())
    return sink_id
