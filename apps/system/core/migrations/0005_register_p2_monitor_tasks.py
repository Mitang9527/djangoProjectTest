"""注册 P2 监控类周期任务（ERROR 突增 / 长事务 / 安全审计 / 健康日报）。

在 0004 已填平"调度真空"的基础上，补充监控闭环所需的 4 个周期任务：
  - core.tasks.check_error_spike         每 5 分钟  (loguru 错误窗口计数 + 阈值告警)
  - core.tasks.check_long_transactions   每 5 分钟  (PostgreSQL 长事务检测)
  - key_management.security_audit        每日 03:10 (TLS 证书到期 + 密钥泄漏 + 密钥年龄)
  - core.tasks.daily_health_report       每日 09:00 (汇总指标推钉钉/飞书)

依赖 0004（django_celery_beat 表已就绪）。
"""
from django.db import migrations
from django_celery_beat.models import (
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
)


def create_beat_schedules(apps, schema_editor):
    every_5min, _ = IntervalSchedule.objects.get_or_create(
        every=5, period=IntervalSchedule.MINUTES
    )
    daily_3_10am, _ = CrontabSchedule.objects.get_or_create(hour=3, minute=10)
    daily_9am, _ = CrontabSchedule.objects.get_or_create(hour=9, minute=0)

    # 若 0004 已建立同名调度则跳过，避免重复创建
    schedules = [
        ("check-error-spike", "core.tasks.check_error_spike", {"interval": every_5min}),
        ("check-long-transactions", "core.tasks.check_long_transactions", {"interval": every_5min}),
        ("security-audit", "key_management.security_audit", {"crontab": daily_3_10am}),
        ("daily-health-report", "core.tasks.daily_health_report", {"crontab": daily_9am}),
    ]
    for name, task, sched in schedules:
        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={"task": task, "enabled": True, **sched},
        )


def remove_beat_schedules(apps, schema_editor):
    PeriodicTask.objects.filter(
        name__in=[
            "check-error-spike",
            "check-long-transactions",
            "security-audit",
            "daily-health-report",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_register_beat_schedules"),
    ]

    operations = [
        migrations.RunPython(create_beat_schedules, remove_beat_schedules),
    ]
