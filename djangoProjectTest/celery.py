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
