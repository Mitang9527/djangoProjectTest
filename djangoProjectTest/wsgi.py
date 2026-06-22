"""
WSGI config for djangoProjectTest project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

# 统一加载环境变量
from utils.env_loader import load_env_file, get_env_type
load_env_file()

# 获取环境类型，决定加载哪个 settings
env_type = get_env_type()
if env_type == "PROD":
    default_settings = "djangoProjectTest.settings.prod"
else:
    default_settings = "djangoProjectTest.settings.dev"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

application = get_wsgi_application()
