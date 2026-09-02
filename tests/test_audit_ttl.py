"""日志 TTL 归档清理（manage.py cleanup_logs）端到端验证。

覆盖：
- 默认 TTL：审计 180 天 / 登录、操作 90 天 → 超期删除、近期保留；
- --days 一次性覆盖保留期；--dry-run 只统计不删除；--table 限定范围；
- 审计日志归档：过期记录复制进 AuditLogArchive（保留原始哈希链）后删除原表；
- 在线审计链重建：清理后 verify_chain_integrity 全绿（无篡改误报）、
  最老剩余记录链根 previous_hash=None、后续记录顺延重算。
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from system.core.models import AuditLog, AuditLogArchive, LoginLog, OperationLog


def _force_created(model, obj, ts):
    """改写 auto_now_add 的 created_at（绕过 save 覆盖，测试夹具专用）。"""
    model.objects.filter(pk=obj.pk).update(created_at=ts)


def _rebuild_chain():
    """按 created_at 重建审计链：created_at 被改写后，哈希需同步才能自洽。"""
    prev = None
    for log in AuditLog.objects.order_by('created_at'):
        log.previous_hash = prev
        log.data_hash = log.compute_hash()
        log.save(update_fields=['previous_hash', 'data_hash'])
        prev = log.data_hash


class CleanupLogsTest(TestCase):
    def setUp(self):
        # 清空日志表：pytest 收集阶段 import test_audit_logs 会注册审计信号，
        # 测试库迁移播种 9 个菜单（0010_menu）时预置 9 条 core.menu 审计，
        # 污染所有对绝对计数的断言。三表均在 is_model_excluded 排除清单内，
        # 删除不会连锁产生新审计，故此处从零起算。
        AuditLog.objects.all().delete()
        LoginLog.objects.all().delete()
        OperationLog.objects.all().delete()

        self.old = timezone.now() - timedelta(days=400)  # 超全部 TTL
        self.mid = timezone.now() - timedelta(days=120)  # >90（login/op）<180（audit）
        self.fresh = timezone.now() - timedelta(days=1)

    # ── 测试数据工厂 ──
    def _audit(self, ts, action='OTHER'):
        obj = AuditLog.objects.create(action=action, log_type='MODEL')
        _force_created(AuditLog, obj, ts)
        return obj

    def _login(self, ts):
        obj = LoginLog.objects.create(email='a@test.com')
        _force_created(LoginLog, obj, ts)
        return obj

    def _op(self, ts):
        obj = OperationLog.objects.create(module='test', method='POST', path='/x', status_code=200)
        _force_created(OperationLog, obj, ts)
        return obj

    def _run(self, **kw):
        out = StringIO()
        call_command('cleanup_logs', stdout=out, **kw)
        return out.getvalue()

    # ── 默认 TTL ──
    def test_default_ttl_purges_expired_keeps_fresh(self):
        self._audit(self.old)
        self._audit(self.mid)
        self._audit(self.fresh)
        self._login(self.old)
        self._login(self.fresh)
        self._op(self.old)
        self._op(self.fresh)

        output = self._run()

        # audit TTL=180：old 删，mid/fresh 留
        self.assertEqual(AuditLog.objects.count(), 2)
        # login/op TTL=90：old+mid 删，fresh 留
        self.assertEqual(LoginLog.objects.count(), 1)
        self.assertEqual(OperationLog.objects.count(), 1)
        self.assertIn('清理完成', output)

    def test_days_override(self):
        self._audit(self.old)
        self._audit(self.mid)
        self._audit(self.fresh)
        output = self._run(days=100)
        self.assertEqual(AuditLog.objects.count(), 1)  # 400d 与 120d 都超 100d
        self.assertIn('100', output)

    def test_dry_run_does_not_delete(self):
        self._audit(self.old)
        self._login(self.old)
        output = self._run(dry_run=True)
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertEqual(LoginLog.objects.count(), 1)
        self.assertIn('dry-run', output)

    def test_table_filter(self):
        self._audit(self.old)
        self._login(self.old)
        self._run(table='login')
        self.assertEqual(AuditLog.objects.count(), 1)  # 审计不受影响
        self.assertEqual(LoginLog.objects.count(), 0)

    def test_no_expired_logs_skips(self):
        self._audit(self.fresh)
        output = self._run()
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertIn('跳过', output)

    # ── 审计归档 + 链重建 ──
    def test_audit_archived_with_original_chain(self):
        old1 = self._audit(self.old, action='CREATE')
        old2 = self._audit(self.old + timedelta(seconds=1), action='UPDATE')
        _rebuild_chain()
        old1.refresh_from_db()
        old2.refresh_from_db()
        h1, h2 = old1.data_hash, old2.data_hash
        self.assertEqual(old2.previous_hash, h1)  # 夹具链自洽

        self._run()

        # 归档表保留原始哈希链与字段
        archived = list(AuditLogArchive.objects.order_by('created_at'))
        self.assertEqual(len(archived), 2)
        self.assertEqual(archived[0].data_hash, h1)
        self.assertEqual(archived[1].data_hash, h2)
        self.assertEqual(archived[1].previous_hash, h1)
        self.assertEqual(archived[0].action, 'CREATE')
        self.assertIsNotNone(archived[0].archived_at)
        # 原表已清空
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_audit_chain_rebuilt_after_purge(self):
        self._audit(self.old, action='CREATE')   # 将被归档 + 删除
        self._audit(self.mid, action='UPDATE')   # 存活边界 → 新链根
        self._audit(self.fresh, action='DELETE')  # 存活
        _rebuild_chain()

        self._run()

        live = list(AuditLog.objects.order_by('created_at'))
        self.assertEqual(len(live), 2)
        self.assertIsNone(live[0].previous_hash)                        # 边界重置为链根
        self.assertEqual(live[1].previous_hash, live[0].data_hash)      # 后续顺延重算
        # 在线链完整性验证全绿（无篡改误报）
        self.assertEqual(AuditLog.verify_chain_integrity(), [])
