#!/usr/bin/env python
"""
Django 创建超级管理员脚本
自动创建默认管理员账户

支持三种密码来源 (按优先级):
  1. 环境变量 DJANGO_SUPERUSER_PASSWORD
  2. 交互式输入 (TTY)
  3. 随机生成 (非 TTY 且未设环境变量)
"""
import os
import sys
import secrets

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
from django.conf import settings

# 初始化 Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.dev')
django.setup()

from loguru import logger
from getpass import getpass


def create_admin():
    """创建管理员用户"""
    logger.info("========================================")
    logger.info("创建管理员用户")
    logger.info("========================================")
    
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # 检查是否已有管理员
        if User.objects.filter(is_superuser=True).exists():
            logger.info("检测到已存在管理员用户，跳过创建")
            return
        
        # 默认配置
        default_username = 'admin'
        default_email = 'admin@example.com'
        
        # 尝试从环境变量获取
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', default_username)
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', default_email)
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', None)
        is_random_password = False
        
        # 如果环境变量没有密码，使用交互式输入或随机生成
        if not password:
            if sys.stdin.isatty():
                # 交互式输入
                print("请设置管理员账户:")
                username = input(f"用户名 [{default_username}]: ").strip() or default_username
                email = input(f"邮箱 [{default_email}]: ").strip() or default_email
                while True:
                    password1 = getpass("密码: ")
                    password2 = getpass("确认密码: ")
                    if password1 == password2:
                        password = password1
                        break
                    print("密码不一致，请重新输入")
            else:
                # 非交互式，生成随机密码
                password = secrets.token_urlsafe(16)
                is_random_password = True
                logger.warning("未检测到 TTY 且未设置 DJANGO_SUPERUSER_PASSWORD，已生成随机密码")
        
        # 创建用户
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )
        
        logger.success(f"管理员用户创建成功!")
        logger.info(f"用户名: {username}")
        logger.info(f"邮箱: {email}")
        if is_random_password:
            print(f"  随机密码 (仅显示一次): {password}")
            logger.warning("请立即登录后台修改密码!")
        
    except Exception as e:
        logger.error(f"创建管理员失败: {e}")
        raise


if __name__ == '__main__':
    create_admin()
