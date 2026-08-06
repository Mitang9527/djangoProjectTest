"""
Core 应用 Celery 任务
"""
from celery import shared_task
from loguru import logger
from datetime import datetime

from .backup import BackupManager


@shared_task(name="core.tasks.auto_backup_database")
def auto_backup_database():
    """自动定时备份数据库"""
    try:
        manager = BackupManager()
        backup = manager.backup_database(name="auto_db_backup")
        logger.info(f"Auto database backup completed: {backup.id}")
        return backup.id
    except Exception as e:
        logger.error(f"Auto database backup failed: {e}")
        raise


@shared_task(name="core.tasks.cleanup_old_backups")
def cleanup_old_backups(retention_days: int = 30):
    """清理旧备份"""
    try:
        from datetime import timedelta
        manager = BackupManager()
        backups = manager.list_backups()
        
        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0
        
        for backup in backups:
            if backup.created_at < cutoff:
                manager.delete_backup(backup.id)
                deleted_count += 1
        
        logger.info(f"Cleaned up {deleted_count} old backups")
        return deleted_count
    except Exception as e:
        logger.error(f"Backup cleanup failed: {e}")
        raise


@shared_task(name="core.tasks.probe_dependencies")
def probe_dependencies():
    """主动探活依赖组件（DB / Redis / Celery Broker / 磁盘），失败时经 alert_system 发告警。

    复用 apps/core/health.py 的 HealthChecker，对每个 FAIL 的组件调用
    AlertEngine.trigger 创建告警（并按 settings.ALERT_PROBE_CHANNELS 外发）。
    建议由 Celery Beat 每 5 分钟调度一次（见 core 的 data migration 注册）。
    """
    from django.conf import settings

    from business.alert_system.services.alert_engine import AlertEngine
    from system.core.health import HealthChecker, HealthStatus

    result = HealthChecker().run_all()
    checks = result.get("checks", {})
    failed = [
        name
        for name, info in checks.items()
        if info.get("status") == HealthStatus.FAIL.value
    ]
    channels = list(getattr(settings, "ALERT_PROBE_CHANNELS", []))

    if failed:
        title = f"依赖组件探活失败: {', '.join(failed)}"
        content = "探活明细: " + "; ".join(
            f"{n}={checks[n].get('message', '')}" for n in failed
        )
        AlertEngine.trigger(
            title=title,
            content=content,
            level="error",
            channels=channels,
            context={"failed": failed, "probe": "dependencies"},
        )
        logger.error(title)
    else:
        logger.info("依赖组件探活全部通过")

    return result


# 错误突增告警冷却（避免每个窗口都触发）
_error_spike_alert_lock = __import__("threading").Lock()
_error_spike_alert_last: float = 0.0


@shared_task(name="core.tasks.check_error_spike")
def check_error_spike():
    """
    ERROR 日志突增检查（每 5 分钟）。

    读取 loguru 错误计数 sink 的窗口统计，超过阈值且过冷却期则经 alert_system 告警。
    注意：计数 sink 在每个进程独立，本任务运行于 beat worker，统计的是该 worker
    进程内的 ERROR；跨进程聚合由 Prometheus(django_error_logs_total) + Alertmanager 完成。
    """
    from django.conf import settings
    from framework.log_utils.error_spike import error_spike_monitor
    from framework.metrics import set_error_logs_window

    threshold = int(getattr(settings, "ALERT_ERROR_SPIKE_THRESHOLD", 50))
    window = int(getattr(settings, "ALERT_ERROR_SPIKE_WINDOW", 300))
    cooldown = int(getattr(settings, "ALERT_ERROR_SPIKE_COOLDOWN", 3600))

    count = error_spike_monitor.count_in_window()
    set_error_logs_window(count)
    logger.info(f"[ErrorSpike] 窗口({window}s)内 ERROR 计数={count}, 阈值={threshold}")

    if count >= threshold:
        now = __import__("time").monotonic()
        with _error_spike_alert_lock:
            global _error_spike_alert_last
            if now - _error_spike_alert_last < cooldown:
                return {"count": count, "alerted": False, "reason": "cooldown"}
            _error_spike_alert_last = now
        AlertEngine.trigger(
            title=f"ERROR 日志突增: {count}/{window}s (阈值 {threshold})",
            content=(
                f"最近 {window} 秒内本进程捕获 {count} 条 ERROR+ 日志，"
                f"超过阈值 {threshold}。请排查近期发布/依赖/流量变化。"
            ),
            level="error",
            channels=list(getattr(settings, "ALERT_ERROR_SPIKE_CHANNELS", []) or []),
            context={"scan": "error_spike", "count": count, "window": window},
        )
        return {"count": count, "alerted": True}

    return {"count": count, "alerted": False}


@shared_task(name="core.tasks.check_long_transactions")
def check_long_transactions():
    """
    长事务检查（每 5 分钟）。

    直接查询 PostgreSQL pg_stat_activity 中 opened 超过阈值的事务
    （数据库原生，跨连接可靠），设置指标并经 alert_system 告警。
    非 PostgreSQL 自动跳过。
    """
    from django.conf import settings
    from framework.db.monitoring import get_long_transactions
    from framework.metrics import set_long_transactions

    alias = getattr(settings, "DB_LONG_TX_ALIAS", "default")
    threshold = int(getattr(settings, "DB_LONG_TX_THRESHOLD", 30))

    found = get_long_transactions(alias=alias, threshold_seconds=threshold)
    set_long_transactions(alias, len(found))

    if found:
        # 仅展示前 10 条
        lines = [
            f"- pid={r.get('pid')} dur={r.get('duration_seconds'):.1f}s "
            f"user={r.get('usename')} state={r.get('state')}"
            for r in found[:10]
        ]
        more = len(found) - len(lines)
        if more > 0:
            lines.append(f"... 另有 {more} 条")
        AlertEngine.trigger(
            title=f"长事务告警: {len(found)} 个 (>{threshold}s)",
            content="检测到长时间未提交的事务:\n" + "\n".join(lines),
            level="warning",
            channels=[],
            context={"scan": "long_tx", "alias": alias, "count": len(found)},
        )
        logger.warning(f"[LongTx] 发现 {len(found)} 个长事务")
    else:
        logger.info("[LongTx] 无长事务")

    return {"alias": alias, "long_transactions": len(found)}


@shared_task(name="core.tasks.daily_health_report")
def daily_health_report():
    """
    每日系统健康日报（每日 09:00）。

    汇总：ERROR 窗口计数、DB 连接池指标、今日告警、Celery 队列积压、依赖健康，
    经钉钉/飞书推送（按 settings.DAILY_REPORT_DINGTALK / DAILY_REPORT_FEISHU 开关）。
    """
    from django.conf import settings
    from django.utils import timezone

    from framework.log_utils.error_spike import error_spike_monitor
    from framework.db import pool_manager
    from framework.metrics import set_celery_queue_backlog, CELERY_QUEUE_BACKLOG
    from business.alert_system.models import AlertHistory
    from system.core.health import HealthChecker, HealthStatus

    now = timezone.now()
    today = now.date()

    # 1) ERROR 计数
    error_count = error_spike_monitor.total()

    # 2) DB 连接池
    try:
        db_stats = pool_manager.all_stats()
    except Exception:
        db_stats = {}

    # 3) 今日告警
    try:
        todays = AlertHistory.objects.filter(first_occurred_at__date=today)
        alert_total = todays.count()
        alert_unresolved = todays.filter(resolved=False).count()
        alert_critical = todays.filter(level="critical").count()
    except Exception:
        alert_total = alert_unresolved = alert_critical = -1

    # 4) Celery 队列积压
    backlog = _collect_celery_backlog()
    for q, n in backlog.items():
        set_celery_queue_backlog(q, n)

    # 5) 依赖健康
    try:
        health = HealthChecker().run_all()
        failed = [
            n for n, i in health.get("checks", {}).items()
            if i.get("status") == HealthStatus.FAIL.value
        ]
    except Exception:
        failed = ["(health check error)"]

    # 组装报告
    lines = [
        f"## 系统健康日报 ({now.strftime('%Y-%m-%d %H:%M')})",
        "",
        f"- ERROR 累计(本进程): **{error_count}**",
        f"- 今日告警: 共 **{alert_total}** / 未解决 **{alert_unresolved}** / 严重 **{alert_critical}**",
        f"- 依赖健康: {'✅ 全部正常' if not failed else '❌ ' + ', '.join(failed)}",
        f"- Celery 积压: {backlog or 'N/A'}",
        "",
        "### DB 连接池",
    ]
    if db_stats:
        for alias, st in db_stats.items():
            m = st.get("metrics", {})
            lines.append(
                f"- `{alias}`: 创建={st.get('created')} 活跃={st.get('active')} "
                f"命中率={m.get('hit_rate')} 错误={m.get('error_count')} 超时={m.get('timeout_count')}"
            )
    else:
        lines.append("- (连接池未启用或无数据)")

    report = "\n".join(lines)

    # 推送
    sent = []
    if getattr(settings, "DAILY_REPORT_DINGTALK", True):
        try:
            from framework.notice_utils.dingtalk_control import DingTalkSendMsg
            if getattr(settings, "DINGTALK_WEBHOOK", ""):
                DingTalkSendMsg().send_markdown(
                    title="系统健康日报", msg=report, is_at_all=False
                )
                sent.append("dingtalk")
        except Exception as e:
            logger.error(f"[DailyReport] 钉钉推送失败: {e}")
    if getattr(settings, "DAILY_REPORT_FEISHU", True):
        try:
            from framework.notice_utils.feishu_control import FeiShuTalkChatBot
            if getattr(settings, "FEISHU_WEBHOOK", ""):
                FeiShuTalkChatBot().send_text(report)
                sent.append("feishu")
        except Exception as e:
            logger.error(f"[DailyReport] 飞书推送失败: {e}")

    logger.info(f"[DailyReport] 已推送至: {sent or '无(未配置 webhook)'}")
    return {"sent": sent, "alert_total": alert_total}


def _collect_celery_backlog() -> dict:
    """收集 Celery 各队列积压（reserved+active 近似）。Broker 不可达时返回空。"""
    try:
        from djangoProjectTest.celery import app as celery_app
        inspect = celery_app.control.inspect(timeout=2)
        reserved = inspect.reserved() or {}
        active = inspect.active() or {}
        # 合并统计（worker -> 任务列表）
        per_queue = {}
        for tasks in list(reserved.values()) + list(active.values()):
            for t in tasks:
                q = (t.get("delivery_info") or {}).get("routing_key") or "default"
                per_queue[q] = per_queue.get(q, 0) + 1
        return per_queue
    except Exception as e:
        logger.debug(f"[DailyReport] 无法获取 Celery 积压: {e}")
        return {}
