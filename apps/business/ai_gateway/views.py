"""AI 网关 - 视图。

职责：作为主平台对外入口，把前端的生成请求经 RabbitMQ 投递给 AI 服务，并立即
返回 task_id；实时结果由前端持 task_id 连 AI 服务 WebSocket 主动获取。

投递目标队列：ai_studio.generate（AI 服务 worker 监听）。
跨服务认证靠主平台与 AI 服务共享的 JWT_SIGNING_KEY：本服务把当前用户的
user_id / username 放进消息体，AI 服务据此归属额度；AI 服务 WS 用同一把密钥
校验连接上的 JWT。
"""
import uuid

from rest_framework import permissions, views
from rest_framework.response import Response

from djangoProjectTest.celery import app as celery_app

from .models import AiStudioTask
from .serializers import GenerationRequestSerializer

# AI 服务消费该队列（见 services/ai_studio/ai_studio_service/settings.py CELERY_TASK_ROUTES）
AI_STUDIO_QUEUE = "ai_studio.generate"
AI_STUDIO_TASK = "ai_studio_app.tasks.handle_generation"


class GenerateView(views.APIView):
    """提交生成任务：投递到 RabbitMQ 并返回 task_id。"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = GenerationRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        task_id = str(uuid.uuid4())
        payload = {
            "user_id": str(request.user.id),
            "username": request.user.username,
            "task_id": task_id,
        }
        payload.update(ser.validated_data)

        try:
            celery_app.send_task(AI_STUDIO_TASK, args=[payload], queue=AI_STUDIO_QUEUE)
        except Exception as exc:  # 队列不可用（如未配置 CELERY_BROKER_URL）
            return Response(
                {
                    "detail": "AI 任务队列不可用，请检查 CELERY_BROKER_URL 是否指向 RabbitMQ",
                    "error": str(exc),
                },
                status=503,
            )

        AiStudioTask.objects.create(
            id=uuid.UUID(task_id),
            user=request.user,
            status="PENDING",
            params=ser.validated_data,
        )
        return Response({"task_id": task_id, "status": "PENDING"})


class TaskStatusView(views.APIView):
    """查询本地提交镜像（实时状态请以 AI 服务 WebSocket 推送为准）。"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, task_id):
        task = AiStudioTask.objects.filter(id=task_id, user=request.user).first()
        if not task:
            return Response({"detail": "任务不存在"}, status=404)
        return Response({
            "task_id": str(task.id),
            "status": task.status,
            "params": task.params,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        })
