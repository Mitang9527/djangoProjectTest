from loguru import logger
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import Soul
from .serializers import SoulSerializer, SoulTestSerializer
from django.utils import timezone
from utils.mixins.audit_mixin import AuditLogMixin

@extend_schema_view(
    list=extend_schema(summary="获取Soul列表", tags=["soul"]),
    create=extend_schema(summary="创建Soul", tags=["soul"]),
    retrieve=extend_schema(summary="获取Soul详情", tags=["soul"]),
    update=extend_schema(summary="更新Soul", tags=["soul"]),
    partial_update=extend_schema(summary="部分更新Soul", tags=["soul"]),
    destroy=extend_schema(summary="删除Soul", tags=["soul"]),
)
class SoulViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    soul 模块接口
    
    提供 Soul 模型的增删改查标准 API。
    """
    queryset = Soul.objects.all()
    serializer_class = SoulSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Soul 模块自定义测试接口",
        description="演示如何在 ViewSet 中添加额外的自定义测试接口。",
        responses={200: SoulTestSerializer},
        tags=["soul"]
    )
    @action(detail=False, methods=['get'])
    def test(self, request):
        """自定义测试逻辑"""
        data = {
            "info": "Soul 模块自定义测试成功！",
            "timestamp": timezone.now()
        }
        serializer = SoulTestSerializer(data)
        logger.info("Soul 模块自定义测试成功")
        return Response(serializer.data)
