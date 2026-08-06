"""Celery 应用定义（独立通知服务）。

worker 启动命令：celery -A notice_service worker -l info -Q notice.send
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "notice_service.settings")

app = Celery("notice_service")
# 使用 Django settings 中 CELERY_ 前缀的配置
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"debug_task run on {self.request.id}")
