import argparse
from django.core.management.base import BaseCommand
from django.conf import settings
from framework.files.upload.tasks import clean_temp_files, clean_old_uploads


class Command(BaseCommand):
    help = '清理临时文件和旧上传文件'

    def add_arguments(self, parser):
        parser.add_argument(
            '--temp',
            action='store_true',
            help='只清理临时文件'
        )
        parser.add_argument(
            '--uploads',
            action='store_true',
            help='只清理旧上传文件'
        )
        parser.add_argument(
            '--temp-hours',
            type=int,
            default=getattr(settings, 'TEMP_FILE_MAX_AGE_HOURS', 24),
            help='临时文件最大保留时间（小时）'
        )
        parser.add_argument(
            '--upload-days',
            type=int,
            default=getattr(settings, 'OLD_UPLOAD_MAX_AGE_DAYS', 30),
            help='旧上传文件最大保留天数'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='模拟运行，不实际删除文件'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('开始清理文件...'))

        temp_only = options['temp']
        uploads_only = options['uploads']
        temp_hours = options['temp_hours']
        upload_days = options['upload_days']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  模拟运行模式，不会实际删除文件'))

        if not uploads_only:
            self.stdout.write(f'\n清理临时文件（保留 {temp_hours} 小时）...')
            temp_result = clean_temp_files(
                max_age_hours=temp_hours,
                dry_run=dry_run
            )
            self._print_stats('临时文件', temp_result)

        if not temp_only:
            self.stdout.write(f'\n清理旧上传文件（保留 {upload_days} 天）...')
            uploads_result = clean_old_uploads(
                max_age_days=upload_days,
                dry_run=dry_run
            )
            self._print_stats('旧上传文件', uploads_result)

        self.stdout.write(self.style.SUCCESS('\n✅ 清理任务完成！'))

    def _print_stats(self, label: str, stats: dict):
        self.stdout.write(f'📊 {label} 统计:')
        self.stdout.write(f'   扫描目录: {stats["directories_scanned"]}')
        self.stdout.write(f'   删除文件: {stats["files_deleted"]}')
        self.stdout.write(f'   释放空间: {stats["bytes_freed"] / 1024 / 1024:.2f} MB')
        
        if stats['errors']:
            self.stdout.write(self.style.ERROR(f'   错误数: {len(stats["errors"])}'))
            for error in stats['errors'][:5]:
                self.stdout.write(self.style.ERROR(f'     - {error}'))
