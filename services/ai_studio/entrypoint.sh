#!/usr/bin/env bash
set -e

# 等待依赖可用（可选，compose 已用 healthcheck 控制顺序）
python manage.py migrate --noinput

# 启动模式：worker 跑 Celery，其它情况跑 gunicorn API
MODE="${1:-api}"
if [ "$MODE" = "worker" ]; then
  exec celery -A ai_studio_service worker -l info
else
  exec gunicorn ai_studio_service.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
fi
