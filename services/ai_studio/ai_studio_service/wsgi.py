import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_studio_service.settings")

# 服务启动横幅 + 依赖/配置启动检查（framework 未挂载到路径时降级为简单打印，不阻断启动）
try:
    from framework.log_utils.service_banner import startup_boot
except Exception:  # framework 未挂载到路径时 (本地子服务) 降级为简单打印
    def startup_boot(service, extra=None, checks=None, fatal=None):
        print(f"\n=== SERVICE START: {service} ===\n", flush=True)
        return True
startup_boot("ai_studio")

application = get_wsgi_application()
