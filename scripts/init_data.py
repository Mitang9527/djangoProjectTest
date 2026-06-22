#!/usr/bin/env python
"""
Django 项目初始化数据脚本
用于创建默认数据、配置等
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

from loguru import logger


def init_data():
    """初始化基础数据"""
    logger.info("========================================")
    logger.info("初始化项目数据")
    logger.info("========================================")
    
    # 检查是否已安装应用
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
    except Exception as e:
        logger.error(f"获取 User 模型失败: {e}")
        return
    
    try:
        # 检查是否已有数据
        if User.objects.filter(is_superuser=True).exists():
            logger.info("检测到已存在管理员用户，跳过基础数据初始化")
            return
        
        # 这里可以添加你的初始化数据逻辑
        # 例如：
        # 1. 创建默认用户组
        # 2. 创建系统配置
        # 3. 创建默认分类等
        
        logger.success("基础数据初始化完成")
        
    except Exception as e:
        logger.error(f"初始化数据时出错: {e}")
        raise


if __name__ == '__main__':
    init_data()
