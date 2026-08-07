"""注册 Celery Beat 周期任务（一次性填平"调度真空"）。

此前项目已定义多个 @shared_task（告警升级、DB 备份/清理、密钥轮换、临时/旧文件清理）
以及本次新增的依赖探活任务，但均未在 django_celery_beat 中建立 PeriodicTask 记录，
导致 Beat 实际调度的周期任务为 0。本迁移统一注册，使这些任务按预期周期运行。

依赖 django_celery_beat 的 0001_initial（Django 会自动应用其后续迁移）。
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
    every_1h, _ = IntervalSchedule.objects.get_or_create(
        every=1, period=IntervalSchedule.HOURS
    )
    daily_2am, _ = CrontabSchedule.objects.get_or_create(hour=2, minute=0)
    daily_3am, _ = CrontabSchedule.objects.get_or_create(hour=3, minute=0)
    daily_5am, _ = CrontabSchedule.objects.get_or_create(hour=5, minute=0)
    weekly_sun_4am, _ = CrontabSchedule.objects.get_or_create(
        hour=4, minute=0, day_of_week=0
    )

    schedules = [
        # 主动探活依赖组件，失败自动经 alert_system 告警
        ("probe-dependencies", "core.tasks.probe_dependencies", {"interval": every_5min}),
        # 告警升级检查
        ("alert-escalation-check", "alert_system.check_escalations", {"interval": every_5min}),
        # 每日凌晨自动备份数据库
        ("auto-backup-database", "core.tasks.auto_backup_database", {"crontab": daily_3am}),
        # 每周日清理旧备份
        ("cleanup-old-backups", "core.tasks.cleanup_old_backups", {"crontab": weekly_sun_4am}),
        # 每日检查并轮换密钥（函数内部判断周期）
        ("auto-rotate-secret-key", "key_management.auto_rotate_secret_key", {"crontab": daily_2am}),
        # 每小时清理临时文件
        ("clean-temp-files", "files.clean_temp_files", {"interval": every_1h}),
        # 每日清理旧上传文件
        ("clean-old-uploads", "files.clean_old_uploads", {"crontab": daily_5am}),
    ]
    for name, task, sched in schedules:
        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={"task": task, "enabled": True, **sched},
        )


def remove_beat_schedules(apps, schema_editor):
    PeriodicTask.objects.filter(
        name__in=[
            "probe-dependencies",
            "alert-escalation-check",
            "auto-backup-database",
            "cleanup-old-backups",
            "auto-rotate-secret-key",
            "clean-temp-files",
            "clean-old-uploads",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        (
            "core",
            "0003_rename_core_audit_action_created_idx_core_audit__action_5c03c3_idx_and_more",
        ),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_beat_schedules, remove_beat_schedules),
    ]
