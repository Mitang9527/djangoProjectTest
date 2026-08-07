import os
import sys
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / 'apps'))

# 加载环境变量
from framework.core.env_loader import load_env_file, get_env_type
load_env_file()

# 获取环境类型，决定加载哪个 settings
env_type = get_env_type()
if env_type == "PROD":
    default_settings = "djangoProjectTest.settings.prod"
else:
    default_settings = "djangoProjectTest.settings.dev"

os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings)

import django
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

admins = User.objects.filter(is_superuser=True)

if admins.exists():
    print('Have admin accounts:')
    for admin in admins:
        print(f'  - Username: {admin.username}, Email: {admin.email}')
else:
    print('No admin accounts found, creating one...')

    # 从环境变量获取密码，否则生成随机安全密码
    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
    if not password:
        password = secrets.token_urlsafe(16)
        print('(未设置 DJANGO_SUPERUSER_PASSWORD 环境变量，已生成随机密码)')

    username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
    email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')

    admin = User.objects.create_superuser(
        username=username,
        email=email,
        password=password
    )
    print(f'Successfully created admin account:')
    print(f'  - Username: {username}')
    print(f'  - Password: {password}')
    print(f'  *** 请立即登录后台修改密码! ***')

