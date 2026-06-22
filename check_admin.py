import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / 'apps'))

# 加载环境变量
from utils.env_loader import load_env_file, get_env_type
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
    # 创建一个测试管理员账号
    admin = User.objects.create_superuser(
        username='admin',
        email='admin@example.com',
        password='admin123456'
    )
    print(f'Successfully created admin account:')
    print(f'  - Username: admin')
    print(f'  - Password: admin123456')