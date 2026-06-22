#!/usr/bin/env python
"""
Django 数据同步脚本
用于在不同环境间同步数据
"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
from django.conf import settings

# 初始化 Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.dev')
django.setup()

import argparse
from loguru import logger
from django.core.management import call_command


def sync_data(direction='export', file='data.json'):
    """
    数据同步
    
    Args:
        direction: 'export' (导出) 或 'import' (导入)
        file: 数据文件
    """
    logger.info(f"开始数据{direction}...")
    
    try:
        if direction == 'export':
            logger.info(f"导出数据到: {file}")
            call_command('dumpdata', 
                        '--natural-foreign', 
                        '--natural-primary',
                        '-o', file)
            logger.success(f"数据导出成功: {file}")
        
        elif direction == 'import':
            if not os.path.exists(file):
                logger.error(f"导入文件不存在: {file}")
                return False
            
            logger.info(f"从 {file} 导入数据...")
            call_command('loaddata', file)
            logger.success(f"数据导入成功")
        
        return True
        
    except Exception as e:
        logger.error(f"数据{direction}失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Django 数据同步工具')
    parser.add_argument('action', choices=['export', 'import'], 
                       help='操作类型: export (导出) 或 import (导入)')
    parser.add_argument('--file', '-f', default='data.json',
                       help='数据文件 (默认: data.json)')
    
    args = parser.parse_args()
    
    success = sync_data(args.action, args.file)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
