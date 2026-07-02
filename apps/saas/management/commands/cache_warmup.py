"""
缓存预热管理命令
用法: python manage.py cache_warmup
"""
from django.core.management.base import BaseCommand
from utils.cache import warmup_all, CacheStats
from loguru import logger


class Command(BaseCommand):
    help = "执行缓存预热，预加载热点数据"

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-stats',
            action='store_true',
            help='重置命中率统计',
        )

    def handle(self, *args, **options):
        if options['reset_stats']:
            CacheStats.reset()
            self.stdout.write(self.style.SUCCESS("命中率统计已重置"))
            return

        self.stdout.write("开始缓存预热...")
        results = warmup_all(verbose=True)

        success = sum(1 for v in results.values() if v)
        total = len(results)

        if total == 0:
            self.stdout.write(self.style.WARNING("没有注册的预热任务"))
        elif success == total:
            self.stdout.write(self.style.SUCCESS(f"全部 {total} 个预热任务成功"))
        else:
            failed = total - success
            self.stdout.write(
                self.style.WARNING(f"{success}/{total} 成功, {failed} 失败")
            )
            for name, ok in results.items():
                if not ok:
                    self.stdout.write(self.style.ERROR(f"  失败: {name}"))
