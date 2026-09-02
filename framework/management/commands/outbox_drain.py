"""投递一批 Outbox 待办事件（事务 Outbox worker 入口）。

用法：
    python manage.py outbox_drain [--limit 100] [--max-attempts 8] [--lease 60]

可由系统计划任务 / Celery beat 周期调用；退出码 0 表示执行完成（不代表全成功）。
"""
from django.core.management.base import BaseCommand

from framework.events.worker import dispatch_pending_events


class Command(BaseCommand):
    help = "投递一批 Outbox 待办事件（租约锁 + 指数退避 + 死信）"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="单轮认领上限")
        parser.add_argument("--max-attempts", type=int, default=8, help="投递最大重试次数")
        parser.add_argument("--lease", type=int, default=60, help="租约时长（秒）")

    def handle(self, *args, **options):
        delivered, failed = dispatch_pending_events(
            max_events=options["limit"],
            max_attempts=options["max_attempts"],
            lease_seconds=options["lease"],
        )
        self.stdout.write(
            self.style.SUCCESS(f"Outbox 投递完成: delivered={delivered} failed={failed}")
        )
