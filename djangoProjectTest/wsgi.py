"""
WSGI config for djangoProjectTest project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

# 统一加载环境变量
from framework.core.env_loader import load_env_file, get_env_type
load_env_file()

# 获取环境类型，决定加载哪个 settings
env_type = get_env_type()
if env_type == "PROD":
    default_settings = "djangoProjectTest.settings.prod"
else:
    default_settings = "djangoProjectTest.settings.dev"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
os.environ.setdefault("WORKER_TYPE", "wsgi")

# 服务启动横幅 + 依赖/配置启动检查（framework 缺失时降级为简单打印，不阻断启动）
try:
    from framework.log_utils.service_banner import startup_boot
except Exception:  # pragma: no cover - framework 不可用时降级
    def startup_boot(service, extra=None, checks=None, fatal=None):
        print(f"\n=== SERVICE START: {service} ===\n", flush=True)
        return True
startup_boot("main")

application = get_wsgi_application()
