"""
Celery 应用初始化
启动方式: celery -A djangoProjectTest worker -l info -P gevent
Beat:   celery -A djangoProjectTest beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.base')

app = Celery('djangoProjectTest')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# 服务启动横幅 + 依赖/配置启动检查: worker 启动时标识当前是哪一个 Celery worker，
# 并验证 DB / Redis / broker 连通性。
# 仅在 worker 进程触发, 不影响 web 进程 (runserver 不会触发这两个信号)。
try:
    from framework.log_utils.service_banner import startup_boot
except Exception:  # pragma: no cover - framework 不可用时降级
    def startup_boot(service, extra=None, checks=None, fatal=None):
        print(f"\n=== SERVICE START: {service} ===\n", flush=True)
        return True

from celery import signals as _celery_signals


@_celery_signals.worker_init.connect
def _on_celery_master_init(sender, **kwargs):
    os.environ.setdefault("WORKER_TYPE", "celery")
    startup_boot("celery_main", extra=f"host={getattr(sender, 'hostname', '?')}")


@_celery_signals.worker_process_init.connect
def _on_celery_worker_init(sender, **kwargs):
    os.environ.setdefault("WORKER_TYPE", "celery")
    startup_boot("celery_main", extra=f"host={getattr(sender, 'hostname', '?')}")
