"""
日志保留 TTL 归档清理：删除超过保留期的审计 / 登录 / 操作日志。

背景：审计、登录、操作三类日志持续写入，长期无清理会无限膨胀。
本命令按 ``settings.*_TTL_DAYS``（env 注入，见 model.py global_config）处理
``created_at < now - TTL`` 的旧记录，分表分批执行避免长事务。

- 审计日志（AuditLog）：**归档 + 清理** —— 先把过期记录逐批复制进
  ``AuditLogArchive``（合规保留副本，含原始哈希链），再删除原表记录；
- 登录 / 操作日志（LoginLog / OperationLog）：直接分批删除。

AuditLog 哈希链处理：``AuditLog`` 有 ``previous_hash / data_hash`` 防篡改链，
删除旧记录会让存活链断裂。清理完成后会**级联重建存活记录链**
（最老剩余记录重置为链根，后续记录 previous_hash 顺延重算），
保证 ``verify_chain_integrity`` 对在线表仍全绿。代价为 O(存活记录数) 的
一次 UPDATE 遍历，属夜间维护任务的可接受开销。

用法::

    python manage.py cleanup_logs                    # 三表按默认 TTL 清理
    python manage.py cleanup_logs --table login      # 仅登录日志
    python manage.py cleanup_logs --days 30          # 一次性覆盖保留期（天）
    python manage.py cleanup_logs --dry-run          # 只统计不删除（安全预览）
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from system.core.models import AuditLog, AuditLogArchive, LoginLog, OperationLog


class Command(BaseCommand):
    help = "日志保留 TTL 归档清理：审计归档+清理、登录/操作日志清理（AuditLog 自动重建哈希链）"

    # 表 → (模型, settings 保留期属性, 是否归档)
    TABLES = {
        'audit': (AuditLog, 'AUDIT_LOG_TTL_DAYS', True),
        'login': (LoginLog, 'LOGIN_LOG_TTL_DAYS', False),
        'operation': (OperationLog, 'OPERATION_LOG_TTL_DAYS', False),
    }
    BATCH_SIZE = 500  # 分批归档/删除，避免 SQLite 长事务与锁表

    def add_arguments(self, parser):
        parser.add_argument(
            '--table', choices=[*self.TABLES, 'all'], default='all',
            help='清理范围：audit / login / operation / all（默认 all）',
        )
        parser.add_argument(
            '--days', type=int, default=0,
            help='覆盖保留期（天），0 表示使用 settings 默认值',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='只统计待删数量，不实际删除',
        )

    def handle(self, *args, **options):
        tables = [options['table']] if options['table'] != 'all' else list(self.TABLES)
        dry_run = options['dry_run']
        total_deleted = 0
        total_archived = 0

        for name in tables:
            model, ttl_attr, archive = self.TABLES[name]
            ttl = options['days'] or int(getattr(settings, ttl_attr, 0) or 0)
            cutoff = timezone.now() - timedelta(days=ttl)

            matched = model.objects.filter(created_at__lt=cutoff).count()
            if matched == 0:
                self.stdout.write(f"[{name}] 无超过 {ttl} 天的旧日志，跳过")
                continue

            if dry_run:
                verb = "归档并删除" if archive else "删除"
                self.stdout.write(f"[{name}] 将{verb} {matched} 条超过 {ttl} 天的旧日志（dry-run，未执行）")
                continue

            if archive:
                archived = self._archive(model, cutoff)
                self.stdout.write(f"[{name}] 已归档 {archived} 条过期日志到 AuditLogArchive")
                total_archived += archived

            deleted = self._batch_delete(model, cutoff)
            if model is AuditLog:
                self._rebuild_audit_chain(cutoff)
            self.stdout.write(self.style.SUCCESS(
                f"[{name}] 已删除 {deleted} 条超过 {ttl} 天的旧日志"
            ))
            total_deleted += deleted

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"✓ 清理完成：归档 {total_archived} 条，删除 {total_deleted} 条日志"
            ))

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _archive(self, model, cutoff) -> int:
        """把过期 AuditLog 逐批复制进归档表（保留原始哈希链），返回归档条数。"""
        total = 0
        now = timezone.now()
        fields = [f.name for f in AuditLog._meta.fields if f.name != 'id']
        while True:
            rows = list(model.objects.filter(created_at__lt=cutoff)
                        .order_by('created_at')[:self.BATCH_SIZE])
            if not rows:
                break
            AuditLogArchive.objects.bulk_create([
                AuditLogArchive(**{f: getattr(row, f) for f in fields}, archived_at=now)
                for row in rows
            ])
            total += len(rows)
            model.objects.filter(pk__in=[r.pk for r in rows]).delete()
        return total

    def _batch_delete(self, model, cutoff) -> int:
        """按主键分批删除 created_at < cutoff 的记录，返回删除条数。"""
        total = 0
        while True:
            ids = list(model.objects.filter(created_at__lt=cutoff)
                       .values_list('pk', flat=True)[:self.BATCH_SIZE])
            if not ids:
                break
            deleted, _ = model.objects.filter(pk__in=ids).delete()
            total += deleted
        return total

    @staticmethod
    def _rebuild_audit_chain(cutoff) -> None:
        """清理后级联重建存活审计链：最老剩余记录重置为链根，后续记录顺延重算。

        删除旧记录会使最老剩余记录的 previous_hash 指向已删除记录；直接重置
        其 previous_hash 会改变其 data_hash，进而必须顺延更新整条存活链。
        """
        prev = None
        for log in AuditLog.objects.filter(created_at__gte=cutoff).order_by('created_at'):
            if log.previous_hash != prev:
                log.previous_hash = prev
                log.data_hash = log.compute_hash()
                log.save(update_fields=['previous_hash', 'data_hash'])
            prev = log.data_hash
