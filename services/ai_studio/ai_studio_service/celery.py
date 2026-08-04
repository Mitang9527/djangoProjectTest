"""Celery 应用定义（独立服务）。

worker 启动命令：celery -A ai_studio_service worker -l info
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_studio_service.settings")

app = Celery("ai_studio_service")
# 使用 Django settings 中 CELERY_ 前缀的配置
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"debug_task run on {self.request.id}")
