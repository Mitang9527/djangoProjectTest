"""
DB 慢查询 / 长事务监控
======================

两部分能力：

1. 慢查询监控（全局，对所有后端生效）
   - 通过 patch `django.db.backends.utils.CursorWrapper.execute/executemany`
     透明计时每条 SQL；超过阈值即累计指标 + 采样告警日志。
   - 指标：django_db_query_duration_seconds（Histogram）、django_db_slow_queries_total（Counter）。
   - 由 framework.db.apps.DBPoolConfig.ready() 自动安装（见 apps.py）。

2. 长事务监控（数据库原生，仅 PostgreSQL 可靠）
   - 由 beat 任务 core.tasks.check_long_transactions 调用 get_long_transactions()，
     直接查询 pg_stat_activity 中 opened 超过阈值的事务，经 alert_system 告警。
   - 指标：django_db_long_transactions（Gauge）。

所有指标在 prometheus_client 缺失时自动降级为 no-op（与 framework.metrics 一致）。
"""
from __future__ import annotations

import time
from typing import List, Dict, Any

from loguru import logger

_installed = False


def _record_query(alias: str, duration: float, threshold: float) -> None:
    """记录一次查询耗时，并在超阈值时累计慢查询指标。"""
    try:
        from framework.metrics import (
            observe_db_query_duration,
            record_slow_query,
        )
        observe_db_query_duration(alias, duration)
        if duration >= threshold:
            record_slow_query(alias)
            # 采样日志：避免慢查询风暴刷屏（每 alias 每 60s 最多 1 条告警级日志）
            _maybe_log_slow(alias, duration)
            # 节流告警（每 alias 每 cooldown 秒最多 1 次）
            _maybe_alert_slow(alias, duration)
    except Exception:
        pass


_slow_log_lock = __import__("threading").Lock()
_slow_log_last: Dict[str, float] = {}
_slow_alert_last: Dict[str, float] = {}


def _maybe_log_slow(alias: str, duration: float) -> None:
    now = time.monotonic()
    with _slow_log_lock:
        last = _slow_log_last.get(alias, 0.0)
        if now - last < 60.0:
            return
        _slow_log_last[alias] = now
    logger.warning(
        f"[SlowQuery] alias={alias} 检测到慢查询 duration={duration:.3f}s"
    )


def _maybe_alert_slow(alias: str, duration: float) -> None:
    """
    慢查询告警（带冷却，避免刷屏）。

    由于 Django 多进程部署下 in-process 计数无法跨进程聚合，慢查询告警
    直接在检测点（数据路径）触发，靠冷却 + alert_system 抑制窗口去重。
    同时 django_db_slow_queries_total 指标会被 Prometheus 跨进程聚合，
    可由 rules/django_alerts.yml 做更全局的告警。
    """
    try:
        from django.conf import settings
        if not getattr(settings, "DB_SLOW_QUERY_ALERT", True):
            return
        cooldown = float(getattr(settings, "DB_SLOW_QUERY_ALERT_COOLDOWN", 3600))
    except Exception:
        cooldown = 3600

    now = time.monotonic()
    with _slow_log_lock:
        last = _slow_alert_last.get(alias, 0.0)
        if now - last < cooldown:
            return
        _slow_alert_last[alias] = now

    try:
        from business.alert_system.services.alert_engine import AlertEngine
        AlertEngine.trigger(
            title=f"慢查询告警 (alias={alias})",
            content=(
                f"检测到执行超过阈值的 SQL，耗时约 {duration:.3f}s。"
                f"请检查索引/执行计划或考虑读写分离。"
            ),
            level="warning",
            channels=[],
            context={"scan": "slow_query", "alias": alias, "duration": round(duration, 3)},
        )
    except Exception:
        pass


def install_slow_query_monitor(threshold: float = 1.0) -> bool:
    """
    全局安装慢查询计时（幂等）。

    Args:
        threshold: 慢查询阈值（秒），默认 1.0s。

    Returns:
        是否本次新安装（已安装返回 False）。
    """
    global _installed
    if _installed:
        return False

    try:
        from django.db.backends.utils import CursorWrapper
    except Exception as e:  # pragma: no cover
        logger.warning(f"[SlowQuery] 无法导入 CursorWrapper，跳过安装: {e}")
        return False

    # 全局 patch 对所有后端生效，指标统一以 default 计（如需按 alias 区分可扩展）
    default_alias = "default"

    _orig_execute = CursorWrapper.execute
    _orig_executemany = CursorWrapper.executemany

    def _patched_execute(self, sql, params=None):
        start = time.monotonic()
        try:
            return _orig_execute(self, sql, params)
        finally:
            _record_query(default_alias, time.monotonic() - start, threshold)

    def _patched_executemany(self, sql, param_list):
        start = time.monotonic()
        try:
            return _orig_executemany(self, sql, param_list)
        finally:
            _record_query(default_alias, time.monotonic() - start, threshold)

    CursorWrapper.execute = _patched_execute
    CursorWrapper.executemany = _patched_executemany
    _installed = True
    logger.info(f"[SlowQuery] 已安装全局慢查询监控（阈值={threshold}s）")
    return True


def uninstall_slow_query_monitor() -> None:
    """还原（测试用）。"""
    global _installed
    if not _installed:
        return
    try:
        from django.db.backends.utils import CursorWrapper
        # 注意：无法可靠还原为原始函数（已是 patch 后的引用），此处仅标记未安装
    except Exception:
        pass
    _installed = False


def get_long_transactions(
    alias: str = "default", threshold_seconds: int = 30
) -> List[Dict[str, Any]]:
    """
    查询 PostgreSQL 中执行超过阈值的事务（数据库原生，最可靠）。

    非 PostgreSQL 或未安装 psycopg 时返回空列表（降级）。

    Returns:
        [{"pid": int, "duration_seconds": float, "state": str,
          "query": str, "usename": str, "client_addr": str}, ...]
    """
    from django.db import connections

    try:
        conn = connections[alias]
    except Exception:
        return []

    engine = conn.settings_dict.get("ENGINE", "")
    if "postgres" not in engine:
        return []

    try:
        import psycopg  # noqa
    except ImportError:
        try:
            import psycopg2  # noqa
        except ImportError:
            logger.debug("[LongTx] 未安装 psycopg/psycopg2，跳过长事务检测")
            return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pid,
                       EXTRACT(EPOCH FROM (now() - xact_start)) AS dur,
                       state,
                       usename,
                       client_addr,
                       left(query, 200) AS query
                FROM pg_stat_activity
                WHERE xact_start IS NOT NULL
                  AND state <> 'idle'
                  AND now() - xact_start > (%s * interval '1 second')
                ORDER BY dur DESC
                """,
                [threshold_seconds],
            )
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
        result = []
        for row in rows:
            item = dict(zip(cols, row))
            item["duration_seconds"] = float(item.get("dur") or 0.0)
            result.append(item)
        return result
    except Exception as e:
        logger.warning(f"[LongTx] 查询 pg_stat_activity 失败 (alias={alias}): {e}")
        return []
