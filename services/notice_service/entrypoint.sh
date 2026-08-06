#!/usr/bin/env bash
set -e

# 无状态服务：sqlite 占位，migrate 无实际作用但不应阻断启动
python manage.py migrate --noinput || true

# 启动模式：worker 跑 Celery，其它情况跑 Daphne(ASGI) 提供 HTTP 健康/入队入口
MODE="${1:-api}"
if [ "$MODE" = "worker" ]; then
  # 监听通知队列（send_notification 路由到此）
  exec celery -A notice_service worker -l info -Q "${CELERY_WORKER_QUEUES:-notice.send}"
else
  exec daphne -b 0.0.0.0 -p 8000 notice_service.asgi:application
fi
