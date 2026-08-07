"""AI 创作工作室 - API 视图（独立服务版，身份解耦）

路由（由根路由挂载于 /api/v1/）：
- POST generate/     创建生成任务（冻结额度 -> mock 生成 -> 确认扣减）
- GET  quota/        查询当前用户额度（首次访问自动发放注册赠送额度）
- GET  tasks/        查询当前用户生成任务列表

鉴权：统一由 ServiceJWTAuthentication 处理，request.user 为 AuthUser（含 id / username）。
demo-login 已移除 —— 用户登录与注册由主平台 SSO 负责，本服务只认 JWT。
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import GenerationTask
from .serializers import (
    GenerationCreateSerializer,
    GenerationTaskSerializer,
    QuotaSerializer,
)
from .services import create_generation_task, get_or_create_quota


class GenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = GenerationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            task = create_generation_task(
                request.user.id, request.user.username, ser.validated_data
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        quota = get_or_create_quota(request.user.id, request.user.username)
        return Response({
            "task_id": task.id,
            "status": task.status,
            "cost": task.cost,
            "result_urls": task.result_urls,
            "quota": {"balance": quota.balance, "frozen": quota.frozen},
        })


class QuotaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        quota = get_or_create_quota(request.user.id, request.user.username)
        return Response(QuotaSerializer(quota).data)


class TaskListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = GenerationTask.objects.filter(user_id=request.user.id)
        tasks = qs[:50]
        return Response({
            "tasks": GenerationTaskSerializer(tasks, many=True).data,
            "count": qs.count(),
        })
