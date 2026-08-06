from django.http import HttpResponse
from loguru import logger
from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView
from rest_framework.response import Response
from framework.drf.renderer import CustomRenderer
from rest_framework import permissions
from django.conf import settings
import os
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets, mixins

from framework.helpers.system_config import get_system_info
from framework.helpers.time_utils import nowtime
from framework.cache.view_cache import drf_cache_view, T_5_MINUTES
from .models import AuditLog
from .serializers import AuditLogSerializer, PingSerializer
from .health import HealthChecker

from framework.files.upload.validators import safe_file_upload, FileValidator
from framework.files.upload.image_processor import ImageProcessor
from framework.helpers.decorators import validate_file_upload, validate_image_upload, handle_file_upload_exception

from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class SystemStatusView(APIView):
    """
    系统状态视图 — 返回 JSON 格式的系统状态
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = None

    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        # 统计最近 15 分钟内活跃的用户数（基于 last_login 近似）
        active_threshold = timezone.now() - timedelta(minutes=15)
        active_count = User.objects.filter(is_active=True, last_login__gte=active_threshold).count()

        # 只调用一次 get_system_info()，避免重复 CPU 采样（每次 interval=1s）
        sys_info = get_system_info()
        stats = {
            'cpu_usage': sys_info['cpu']['percent'],
            'mem_usage': sys_info['memory']['percent'],
            'active_users': active_count,
            'last_update': nowtime()
        }
        return Response(stats)


@extend_schema_view(
    list=extend_schema(summary="获取审计日志列表", tags=["审计日志"]),
    retrieve=extend_schema(summary="获取审计日志详情", tags=["审计日志"]),
)
class AuditLogViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    审计日志查看接口
    
    仅允许管理员查看系统操作审计日志。
    """
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAdminUser]


# 接口文档权限检查视图
from django.views.generic import View
from django.http import HttpResponseRedirect
from django.urls import reverse

class AdminRequiredMixin(View):
    """
    管理员权限检查 Mixin
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return Response(
                {'detail': '需要管理员权限'}, status=403
            )
        return super().dispatch(request, *args, **kwargs)


class PingView(APIView):
    """
    连通性测试接口 — 返回 pong，用于快速验证 /api 链路与统一响应格式是否就绪。
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="连通性测试",
        description="返回 pong，用于快速验证 /api 链路与统一响应格式是否就绪",
        tags=["系统"],
    )
    def get(self, request):
        return Response({"ping": "pong", "time": nowtime()})

    @extend_schema(
        summary="连通性测试(POST)",
        description="接收 name 字段并返回问候，演示 POST 请求链路、参数校验与统一返回格式",
        tags=["系统"],
    )
    def post(self, request):
        serializer = PingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        return Response({
            "ping": "pong",
            "method": "POST",
            "message": f"hello, {name}!",
            "received": serializer.validated_data,
        })


class HealthCheckView(APIView):
    """
    健康检查视图 - 系统整体健康状态
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    
    @extend_schema(
        summary="健康检查",
        description="检查系统所有组件的健康状态",
        tags=["系统"]
    )
    def get(self, request):
        checker = HealthChecker()
        result = checker.run_all()
        return Response(result)


class LivenessCheckView(APIView):
    """
    存活检查视图 - K8s liveness probe
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    
    @extend_schema(
        summary="存活检查",
        description="Kubernetes liveness probe",
        tags=["系统"]
    )
    def get(self, request):
        checker = HealthChecker()
        result = checker.run_live()
        return Response(result)


class ReadinessCheckView(APIView):
    """
    就绪检查视图 - K8s readiness probe
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    
    @extend_schema(
        summary="就绪检查",
        description="Kubernetes readiness probe",
        tags=["系统"]
    )
    def get(self, request):
        checker = HealthChecker()
        result = checker.run_ready()
        status_code = 200 if result["status"] == "pass" else 503
        return Response(result, status=status_code)


class FileUploadView(APIView):
    """
    通用文件上传视图示例
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="文件上传",
        description="安全的文件上传接口，包含类型验证和大小限制",
        tags=["文件上传"]
    )
    @validate_file_upload(
        file_field='file',
        max_file_size=settings.FILE_UPLOAD_MAX_FILE_SIZE
    )
    @handle_file_upload_exception
    def post(self, request):
        uploaded_file = request.FILES['file']
        
        file_path = safe_file_upload(
            uploaded_file,
            upload_dir='uploads',
            random_filename=True
        )
        
        return Response({
            'success': True,
            'message': '文件上传成功',
            'file_path': file_path,
            'file_name': uploaded_file.name,
            'file_size': uploaded_file.size
        })


class ImageUploadView(APIView):
    """
    图片上传视图示例（含压缩和水印）
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="图片上传",
        description="图片上传接口，自动压缩并添加水印",
        tags=["文件上传"]
    )
    @validate_image_upload(
        file_field='image',
        max_file_size=settings.FILE_UPLOAD_MAX_FILE_SIZE
    )
    @handle_file_upload_exception
    def post(self, request):
        uploaded_file = request.FILES['image']
        
        # 上传原始图片
        original_path = safe_file_upload(
            uploaded_file,
            upload_dir='images/original',
            random_filename=True
        )
        
        # 处理图片（压缩）
        processor = ImageProcessor(
            max_width=settings.IMAGE_PROCESSING_MAX_WIDTH,
            max_height=settings.IMAGE_PROCESSING_MAX_HEIGHT,
            quality=settings.IMAGE_PROCESSING_QUALITY
        )
        
        compressed_path = processor.compress_image(
            original_path,
            output_path=os.path.join(
                settings.MEDIA_ROOT,
                'images/compressed',
                os.path.basename(original_path)
            )
        )
        
        # 创建缩略图
        thumbnail_path = processor.create_thumbnail(
            original_path,
            output_path=os.path.join(
                settings.MEDIA_ROOT,
                'images/thumbnails',
                os.path.basename(original_path)
            ),
            size=(200, 200)
        )
        
        return Response({
            'success': True,
            'message': '图片上传成功',
            'original': original_path.replace(settings.MEDIA_ROOT, settings.MEDIA_URL),
            'compressed': compressed_path.replace(settings.MEDIA_ROOT, settings.MEDIA_URL),
            'thumbnail': thumbnail_path.replace(settings.MEDIA_ROOT, settings.MEDIA_URL),
            'file_name': uploaded_file.name,
            'file_size': uploaded_file.size
        })
