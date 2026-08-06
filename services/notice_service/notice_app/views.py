"""通知服务 HTTP 入口。

- GET  /api/health/              健康检查
- POST /api/notice/notify/       入队一条通知（经本服务 celery 投递到 notice.send 队列）

说明：正常链路是「主平台 alert_engine → RabbitMQ → 本服务 worker」，HTTP 入口仅作
内部触发/调试用途；若设置了 NOTICE_API_TOKEN，则需带 X-Notice-Token 头。
"""
import os

from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from notice_service.celery import app as celery_app

NOTICE_QUEUE = "notice.send"
NOTICE_TASK = "notice_app.tasks.send_notification"


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class NotifyView(APIView):
    def post(self, request):
        token = os.environ.get("NOTICE_API_TOKEN")
        if token and request.headers.get("X-Notice-Token") != token:
            return Response(
                {"detail": "unauthorized"}, status=http_status.HTTP_401_UNAUTHORIZED
            )

        data = request.data
        payload = {
            "channels": data.get("channels", []),
            "title": data.get("title", ""),
            "content": data.get("content", ""),
            "level": data.get("level", "warning"),
            "context": data.get("context", {}) or {},
        }
        if not payload["channels"]:
            return Response(
                {"detail": "channels 不能为空"}, status=http_status.HTTP_400_BAD_REQUEST
            )

        try:
            celery_app.send_task(NOTICE_TASK, args=[payload], queue=NOTICE_QUEUE)
        except Exception as exc:
            return Response(
                {"detail": "通知队列不可用，请检查 CELERY_BROKER_URL", "error": str(exc)},
                status=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"status": "accepted"}, status=http_status.HTTP_202_ACCEPTED)
