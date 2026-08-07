#!/usr/bin/env bash
set -e

# 等待依赖可用（可选，compose 已用 healthcheck 控制顺序）
python manage.py migrate --noinput

# 启动模式：worker 跑 Celery，其它情况跑 Daphne(ASGI) 同时提供 HTTP + WebSocket
MODE="${1:-api}"
if [ "$MODE" = "worker" ]; then
  # 监听生成队列（handle_generation / generate_task 均路由到此）
  exec celery -A ai_studio_service worker -l info -Q "${CELERY_WORKER_QUEUES:-ai_studio.generate}"
else
  exec daphne -b 0.0.0.0 -p 8000 ai_studio_service.asgi:application
fi
