"""
Django 自定义管理命令：自动轮换 SECRET_KEY

使用方法：
    python manage.py rotate_secret_key --days 30
    python manage.py rotate_secret_key --check-only
"""
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = "轮换 Django SECRET_KEY，支持过渡期"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='旧密钥保留天数（默认30天）'
        )
        parser.add_argument(
            '--check-only',
            action='store_true',
            help='只检查当前密钥状态，不执行轮换'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='强制执行轮换，忽略时间检查'
        )

    def handle(self, *args, **options):
        days = options['days']
        check_only = options['check_only']
        force = options['force']

        # 导入在这里是为了避免过早初始化 Django
        from framework.key_management import get_key_manager

        manager = get_key_manager()

        # 显示当前状态
        self.show_status(manager)

        if check_only:
            logger.info("Check-only 模式，不执行轮换")
            return

        # 检查是否需要轮换
        if not force and not self.should_rotate(manager, days):
            logger.info("当前密钥还不需要轮换")
            return

        # 执行轮换
        logger.info(f"开始轮换密钥，旧密钥保留 {days} 天")
        new_key = manager.rotate_key(keep_old_days=days)
        
        logger.success(f"密钥轮换成功！")
        logger.info(f"新密钥前缀: {new_key[:15]}...")
        
        # 提示更新 .env（可选）
        self.stdout.write(self.style.WARNING(
            "\n建议同时更新 .env 文件中的 SECRET_KEY："
        ))
        self.stdout.write(self.style.SUCCESS(f"SECRET_KEY={new_key}"))

    def show_status(self, manager):
        """显示当前密钥状态"""
        keys_info = manager.get_key_info()
        
        self.stdout.write("\n当前密钥状态：")
        for i, key in enumerate(keys_info, 1):
            status = "主密钥" if key['is_primary'] else "活跃" if key['is_active'] else "已停用"
            color = self.style.SUCCESS if key['is_primary'] else self.style.NOTICE
            
            self.stdout.write(color(
                f"  {i}. [{status}] {key['prefix']} "
                f"(创建于: {key['created_at']})"
            ))

    def should_rotate(self, manager, days):
        """
        判断是否应该轮换密钥
        如果主密钥使用时间超过 days 天，则需要轮换
        """
        keys_info = manager.get_key_info()
        
        # 找到主密钥
        primary_key = None
        for key in keys_info:
            if key['is_primary']:
                primary_key = key
                break
        
        if not primary_key:
            logger.warning("没有找到主密钥，强制执行轮换")
            return True
        
        # 计算密钥使用时间
        try:
            created_at = datetime.fromisoformat(primary_key['created_at'])
            days_old = (datetime.now() - created_at).days
            
            logger.info(f"当前主密钥已使用 {days_old} 天")
            
            if days_old >= days:
                logger.info(f"达到轮换阈值（{days}天）")
                return True
            else:
                logger.info(f"还未到轮换时间（还剩 {days - days_old} 天）")
                return False
                
        except Exception as e:
            logger.error(f"检查密钥时间失败: {e}")
            return False
