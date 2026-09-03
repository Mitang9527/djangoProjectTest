"""核心平台视图层。

集中承载平台级 API 视图：健康检查、文件上传（图片/音频/文档）、API Key 管理、
审计日志、登录/操作日志、数据字典、文件资产、动态菜单、系统信息等。
大部分以 DRF ViewSet 暴露，配合 framework.drf 的鉴权与限流能力使用。
"""

import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from loguru import logger
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from djangoProjectTest.pagination import StandardPagination
from framework.drf.sliding_jwt import SlidingJWTAuthentication
from framework.drf.timed_api_key_auth import TimedAPIKeyAuthentication
from framework.files.upload import FileUploadError, FileValidator, relative_media_url, safe_file_upload
from framework.files.upload.image_processor import ImageProcessor
from framework.helpers.decorators import handle_file_upload_exception, validate_file_upload, validate_image_upload
from framework.helpers.system_config import get_system_info
from framework.helpers.time_utils import nowtime
from system.saas.mixins import TenantQuerysetMixin
from system.saas.permissions import FileManagePermission, FileViewPermission, IsSuperAdmin

from .health import HealthChecker
from .models import APIKey, AuditLog, FileAsset, LoginLog, Menu, OperationLog
from .permissions import CanIssueApiKey, CanManageApiKey
from .serializers import (
    ApiKeySerializer,
    AuditLogSerializer,
    CreateApiKeySerializer,
    DictItemSerializer,
    DictTypeSerializer,
    FileAssetSerializer,
    LoginLogSerializer,
    MenuSerializer,
    OperationLogSerializer,
    PingSerializer,
)

User = get_user_model()


class SystemStatusView(APIView):
    """系统状态视图 — 返回 JSON 格式的系统状态"""
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
    """审计日志查看接口 — 仅允许管理员查看系统操作审计日志。"""
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAdminUser]


def _parse_datetime_param(value):
    """解析 ?created_from= / ?created_to= 查询参数（ISO 格式，非法则 None）"""
    if not value:
        return None
    try:
        from django.utils.dateparse import parse_datetime
        return parse_datetime(value)
    except Exception:
        return None


@extend_schema_view(
    list=extend_schema(
        summary="登录日志分页查询（租户隔离）",
        tags=["审计日志"],
        parameters=[
            {"name": "keyword", "in": "query", "required": False, "schema": {"type": "string"}, "description": "邮箱/IP/失败原因模糊匹配"},
            {"name": "status", "in": "query", "required": False, "schema": {"type": "string"}, "description": "success/failed"},
            {"name": "created_from", "in": "query", "required": False, "schema": {"type": "string", "format": "date-time"}},
            {"name": "created_to", "in": "query", "required": False, "schema": {"type": "string", "format": "date-time"}},
        ],
    ),
    retrieve=extend_schema(summary="登录日志详情", tags=["审计日志"]),
)
class LoginLogViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """登录日志查询（对齐参考 GET /logs/login）：按租户隔离 + keyword/status/时间范围筛选。"""
    queryset = LoginLog.objects.select_related('user', 'tenant').all()
    serializer_class = LoginLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request

        # 租户隔离：管理员无租户上下文看全部；有上下文按 tenant 过滤
        tenant_id = getattr(request, 'tenant_id', None)
        if not tenant_id:
            tenant_id = request.headers.get('X-Tenant-Id') or request.META.get('HTTP_X_TENANT_ID')
        user_role = getattr(request.user, 'role', None)
        is_super = request.user.is_superuser or (
            user_role is not None and getattr(user_role, 'slug', None) in ('super-admin', 'admin')
        )
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        elif not is_super:
            # 普通用户无租户上下文 → 空结果（无权查看全局）
            return queryset.none()

        q = self.request.query_params
        keyword = q.get('keyword', '').strip()
        if keyword:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(email__icontains=keyword)
                | Q(ip__icontains=keyword)
                | Q(failure_reason__icontains=keyword)
            )
        status_val = q.get('status', '').strip()
        if status_val:
            queryset = queryset.filter(status=status_val)
        created_from = _parse_datetime_param(q.get('created_from'))
        if created_from:
            queryset = queryset.filter(created_at__gte=created_from)
        created_to = _parse_datetime_param(q.get('created_to'))
        if created_to:
            queryset = queryset.filter(created_at__lte=created_to)
        return queryset


@extend_schema_view(
    list=extend_schema(
        summary="操作日志分页查询（租户隔离）",
        tags=["审计日志"],
        parameters=[
            {"name": "keyword", "in": "query", "required": False, "schema": {"type": "string"}, "description": "邮箱/模块/路径/IP 模糊匹配"},
            {"name": "method", "in": "query", "required": False, "schema": {"type": "string"}},
            {"name": "status_code", "in": "query", "required": False, "schema": {"type": "integer"}},
            {"name": "created_from", "in": "query", "required": False, "schema": {"type": "string", "format": "date-time"}},
            {"name": "created_to", "in": "query", "required": False, "schema": {"type": "string", "format": "date-time"}},
        ],
    ),
    retrieve=extend_schema(summary="操作日志详情", tags=["审计日志"]),
)
class OperationLogViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """操作日志查询（对齐参考 GET /logs/operation）：按租户隔离 + keyword/method/status_code/时间范围筛选。"""
    queryset = OperationLog.objects.select_related('user', 'tenant').all()
    serializer_class = OperationLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request

        tenant_id = getattr(request, 'tenant_id', None)
        if not tenant_id:
            tenant_id = request.headers.get('X-Tenant-Id') or request.META.get('HTTP_X_TENANT_ID')
        user_role = getattr(request.user, 'role', None)
        is_super = request.user.is_superuser or (
            user_role is not None and getattr(user_role, 'slug', None) in ('super-admin', 'admin')
        )
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        elif not is_super:
            return queryset.none()

        q = self.request.query_params
        keyword = q.get('keyword', '').strip()
        if keyword:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(email__icontains=keyword)
                | Q(module__icontains=keyword)
                | Q(path__icontains=keyword)
                | Q(ip__icontains=keyword)
            )
        method = q.get('method', '').strip().upper()
        if method:
            queryset = queryset.filter(method=method)
        status_code = q.get('status_code', '').strip()
        if status_code and status_code.isdigit():
            queryset = queryset.filter(status_code=int(status_code))
        created_from = _parse_datetime_param(q.get('created_from'))
        if created_from:
            queryset = queryset.filter(created_at__gte=created_from)
        created_to = _parse_datetime_param(q.get('created_to'))
        if created_to:
            queryset = queryset.filter(created_at__lte=created_to)
        return queryset


# 接口文档权限检查视图
from django.views.generic import View


class AdminRequiredMixin(View):
    """管理员权限检查 Mixin"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return Response(
                {"detail": "需要管理员权限"}, status=403
            )
        return super().dispatch(request, *args, **kwargs)


class PingView(APIView):
    """连通性测试接口 — 返回 pong，用于快速验证 /api 链路与统一响应格式是否就绪。"""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="连通性测试",
        description="返回 pong，用于快速验证 /api 链路与统一响应格式是否就绪",
        tags=["系统"],
    )
    def get(self, request):
        return Response({
            "ping": "pong",
            "time": nowtime()
        })

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


class PlatformInfoView(APIView):
    """
    平台信息端点 — GET /api/v1/ 返回平台名称、版本、运行状态、文档地址与环境。
    公开免认证/签名（settings.API_SIGNATURE_EXCLUDE_PATHS 已排除 /api/v1/）；
    响应经 CustomRenderer 包装为 {status, code, message, data, errors}，平台信息落在 data 内。
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="平台信息",
        description="返回平台名称、版本、运行状态、API 文档地址与当前环境（DEV/PROD）",
        tags=["系统"],
    )
    def get(self, request):
        return Response(
            {
                "name": settings.PLATFORM_NAME,
                "version": settings.PLATFORM_VERSION,
                "status": "running",
                "documentation_url": settings.API_DOCS_URL,
                "environment": "DEV" if settings.DEBUG else "PROD"
            }
        )


class PingAuthView(APIView):
    """
    对照演示：permission_classes=[AllowAny] 时「未带 token」也能 200；但配置
    SlidingJWTAuthentication 后 DRF 会尝试解析 Bearer token：带【有效】token 则填充 request.user/auth，
    带【无效/过期】token 由认证层直接 401 拒绝，完全不带则匿名通过
    （认证失败≠禁止，禁止由 permission_classes 决定）。
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = [SlidingJWTAuthentication]

    def get(self, request):
        return Response({
            "ping": "pong1",
            "auth_demo": {
                "authentication_classes": [c.__name__ for c in self.authentication_classes],
                "user": str(request.user),
                "is_authenticated": bool(getattr(request.user, "is_authenticated", False)),
                "auth": str(request.auth),
            },
        })


class SecureInfoView(APIView):
    """
    受时效性密钥保护：须携带**有效且未过期**的 API Key（X-API-Key 或 Bearer）。
    正确性与时效性由 TimedAPIKeyAuthentication 在视图执行前**同步**校验：
    缺失/错误/禁用/过期任一不满足都直接 401，绝不进入本方法返回受保护信息。
    通过后才执行 get()，返回仅持有效密钥可见的数据并附密钥时效信息。
    """

    authentication_classes = [TimedAPIKeyAuthentication]
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="时效性密钥受保护信息",
        description=(
                "携带有效且未过期的 API Key 才能返回受保护信息；"
                "密钥缺失 / 错误 / 已禁用 / 已过期 均返回 401。"
        ),
        tags=["系统"],
    )
    def get(self, request):
        logger.info(f"[SecureInfo] 收到受保护信息请求 | IP: {request.META.get('REMOTE_ADDR')}")

        api_key = getattr(request, "api_key", None)
        remaining_seconds = None

        if api_key and api_key.expires_at:
            remaining_seconds = int((api_key.expires_at - timezone.now()).total_seconds())
            logger.debug(
                f"[SecureInfo] 密钥校验通过 | KeyName: {api_key.name} | "
                f"Owner: {request.user.username} | 剩余有效时间: {remaining_seconds}s"
            )
        else:
            logger.warning("[SecureInfo] 请求通过了认证，但未获取到有效的 api_key 或过期时间！")

        logger.info(f"[SecureInfo] 成功返回受保护数据 | KeyName: {api_key.name if api_key else 'N/A'}")
        return Response({
            "message": "密钥校验通过，返回受保护信息",
            "owner": request.user.username,
            "key_name": api_key.name if api_key else None,
            "expires_at": api_key.expires_at.isoformat() if (api_key and api_key.expires_at) else None,
            "remaining_seconds": remaining_seconds,
            "secret_data": {
                "project": "djangoProjectTest",
                "note": "此数据仅持有效密钥可见",
            },
        })


class ApiKeyViewSet(viewsets.ModelViewSet):
    """
    API Key 生命周期管理（/api/api-keys/）：POST 签发（仅管理员 JWT）、GET 列表（管理员全量/用户仅自己）、
    GET {pk} 详情（脱敏）、PATCH 改名/吊销(is_active=false)/重新启用、DELETE 删除、POST {pk}/rotate/ 轮换。
    安全约定：管理接口一律用真实 JWT（SlidingJWTAuthentication），禁止用 API Key 自身管理，防凭证链式放大；
    明文密钥仅签发/轮换一次性返回，其余一律 masked_key 脱敏；普通用户仅操作自己名下（CanManageApiKey）；
    create 单独由 CanIssueApiKey 管控（仅管理员）。
    """

    serializer_class = ApiKeySerializer
    authentication_classes = [SlidingJWTAuthentication]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_permissions(self):
        # 签发仅管理员；其余生命周期动作归属人或管理员
        if self.action == "create":
            return [CanIssueApiKey()]
        return [CanManageApiKey()]

    def get_queryset(self):
        qs = APIKey.objects.all()
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        return qs

    # 签发（仅管理员）
    @extend_schema(
        summary="签发 API Key",
        description=(
            "管理员签发带时效性的 API Key。明文密钥仅本次返回，库内仅存 SHA256 哈希。"
            "owner_username 省略时归属当前管理员；指定他人时要求管理员身份（本视图已强制）。"
        ),
        tags=["系统"],
        request=CreateApiKeySerializer,
    )
    def create(self, request, *args, **kwargs):
        serializer = CreateApiKeySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owner_username = data.get("owner_username")
        if owner_username:
            try:
                owner = User.objects.get(username=owner_username)
            except User.DoesNotExist:
                return Response(
                    {"detail": f"归属用户不存在: {owner_username}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            owner = request.user

        ttl = data["ttl"] or None
        key_obj = APIKey.issue(owner, data["name"], ttl_seconds=ttl)
        is_permanent = key_obj.expires_at is None

        logger.bind(source="app").info(
            f"[APIKey] 签发密钥 | issuer={request.user.username} | "
            f"owner={owner.username} | name={key_obj.name} | permanent={is_permanent}"
        )
        self._audit(request, key_obj, "CREATE", "SENSITIVE", {
            "name": key_obj.name,
            "owner": owner.username,
            "issuer": request.user.username,
            "expires_at": key_obj.expires_at.isoformat() if key_obj.expires_at else None,
            "is_permanent": is_permanent,
        })

        return Response(
            {
                "key": key_obj.key,  # 明文仅此一次
                "id": key_obj.id,
                "name": key_obj.name,
                "owner": owner.username,
                "masked_key": key_obj.masked_key,
                "expires_at": key_obj.expires_at.isoformat() if key_obj.expires_at else None,
                "is_permanent": is_permanent,
                "note": "明文密钥仅返回一次，请妥善保存；库内仅存哈希，无法再次查询。",
            },
            status=status.HTTP_201_CREATED,
        )

    # 轮换（作废旧密钥，签发新密钥）
    @extend_schema(
        summary="轮换 API Key",
        description=(
            "作废当前密钥并签发新密钥（沿用相同归属与剩余有效期）。"
            "明文仅本次返回；旧密钥立即失效，请立即更换调用方配置。"
        ),
        tags=["系统"],
    )
    @action(detail=True, methods=["post"], url_path="rotate")
    def rotate(self, request, *args, **kwargs):
        old = self.get_object()  # 已校验对象级权限
        # 沿用剩余有效期
        ttl = None
        if old.expires_at:
            ttl = max(int((old.expires_at - timezone.now()).total_seconds()), 0)
        old.is_active = False
        old.save(update_fields=["is_active", "updated_at"])

        key_obj = APIKey.issue(old.user, old.name, ttl_seconds=ttl)
        is_permanent = key_obj.expires_at is None

        logger.bind(source="app").info(
            f"[APIKey] 轮换密钥 | operator={request.user.username} | "
            f"old_id={old.id} | new_id={key_obj.id} | name={key_obj.name}"
        )
        self._audit(request, key_obj, "UPDATE", "SYSTEM", {
            "action": "rotate",
            "old_id": str(old.id),
            "new_id": str(key_obj.id),
            "name": key_obj.name,
            "operator": request.user.username,
            "expires_at": key_obj.expires_at.isoformat() if key_obj.expires_at else None,
            "is_permanent": is_permanent,
        })

        return Response(
            {
                "key": key_obj.key,  # 明文仅此一次
                "id": key_obj.id,
                "name": key_obj.name,
                "masked_key": key_obj.masked_key,
                "expires_at": key_obj.expires_at.isoformat() if key_obj.expires_at else None,
                "is_permanent": is_permanent,
                "note": "旧密钥已作废，请立即更换调用方配置；明文密钥仅返回一次。",
            },
            status=status.HTTP_201_CREATED,
        )

    # 部分更新（改名 / 吊销 / 重新启用）
    def perform_update(self, serializer):
        old = serializer.instance
        was_active = old.is_active
        new = serializer.save()
        changes = {}
        if "is_active" in serializer.validated_data and was_active != new.is_active:
            changes["is_active"] = new.is_active
        if "name" in serializer.validated_data and old.name != new.name:
            changes["name"] = new.name
        if changes:
            self._audit(self.request, new, "UPDATE", "SYSTEM", {
                "action": "update",
                "id": str(new.id),
                "name": new.name,
                "changes": changes,
                "operator": self.request.user.username,
            })

    # 删除（吊销且移除）
    def perform_destroy(self, instance):
        self._audit(self.request, instance, "DELETE", "SENSITIVE", {
            "action": "delete",
            "id": str(instance.id),
            "name": instance.name,
            "operator": self.request.user.username,
        })
        instance.delete()

    # 审计辅助
    def _audit(self, request, key_obj, action, log_type, action_info):
        AuditLog.objects.create(
            user=request.user,
            action=action,
            log_type=log_type,
            target_model="core_apikey",
            target_id=str(key_obj.id),
            action_info=action_info,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            request_path=request.path,
            request_method=request.method,
        )


class HealthCheckView(APIView):
    """健康检查视图 — 系统整体健康状态"""
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
    """存活检查视图 — K8s liveness probe"""
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
    """就绪检查视图 — K8s readiness probe"""
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


# 文件资产登记（FileAsset）——上传成功登记资产，租户配额可执行

def _cleanup_uploaded_files(*paths) -> None:
    """清理已落盘的上传产物（配额拒绝时回滚，避免磁盘残留）。"""
    for p in paths:
        if not p:
            continue
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            logger.warning(f"[FileAsset] 清理失败，请手动删除: {p}")


def _register_file_asset(request, category: str, uploaded_file, *paths) -> None | Response:
    """
    登记一条文件资产；命中租户套餐配额上限时清理已落盘产物并返回 429 拒绝响应。
    一次上传=一条资产（paths 为本次全部落盘产物，拒绝时一并清理）；
    无租户上下文（request.tenant_id 为空）仍登记（tenant 可空）但不做配额检查；
    配额按未删除资产统计：max_file_assets 计数、max_storage_mb 存储量。
    """
    from django.db.models import Sum

    from system.core.models import FileAsset
    from system.saas.models import Tenant

    tenant = None
    tenant_id = getattr(request, 'tenant_id', None)
    if tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id).first()

    if tenant is not None and tenant.plan_id:
        plan = tenant.plan
        assets = FileAsset.objects.filter(tenant=tenant, is_deleted=False)
        # 配额字段用 is not None 判断：0 表示上限为 0（任何上传都拒绝），而非"不限"
        if plan.max_file_assets is not None and assets.count() >= plan.max_file_assets:
            _cleanup_uploaded_files(*paths)
            return Response(
                {"detail": "文件资产数量已达套餐上限", "code": "file_quota_exceeded"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if plan.max_storage_mb is not None:
            used_bytes = assets.aggregate(total=Sum('file_size'))['total'] or 0
            if (used_bytes + (uploaded_file.size or 0)) > plan.max_storage_mb * 1024 * 1024:
                _cleanup_uploaded_files(*paths)
                return Response(
                    {"detail": "存储空间已达套餐上限", "code": "storage_quota_exceeded"},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

    FileAsset.objects.create(
        tenant=tenant,
        user=request.user if getattr(request.user, 'is_authenticated', False) else None,
        category=category,
        file_name=uploaded_file.name or '',
        file_path=paths[0] if paths else '',
        file_size=uploaded_file.size or 0,
        content_type=getattr(uploaded_file, 'content_type', '') or '',
    )
    return None


class DocumentUploadView(APIView):
    """文档上传视图（文档 / 数据 / 归档 / 字体等）"""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="文档上传",
        description="文档类文件上传接口，仅放行文档/数据/归档/字体等已审核格式，含大小限制与扩展名白名单校验",
        tags=["文件上传"]
    )
    @validate_file_upload(
        file_field='file',
        max_file_size=settings.FILE_UPLOAD_MAX_FILE_SIZE,
        # 仅放行文档类白名单（与全局 DEFAULT_DOC_EXTENSIONS 同步，自动跟随白名单维护）
        allowed_extensions=FileValidator.DEFAULT_DOC_EXTENSIONS,
    )
    @handle_file_upload_exception
    def post(self, request):
        # 优雅处理：前端漏传文件时返回 400，而非抛出 MultiValueDictKeyError 导致 500
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {"detail": "缺少文件字段: file"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            file_path = safe_file_upload(
                uploaded_file,
                upload_dir='documents',
                random_filename=True
            )
        except (FileUploadError, OSError) as e:
            # 磁盘满 / 无写入权限等底层错误：服务端记录详情，前端返回安全提示（不泄露路径）
            logger.error(f"[DocumentUpload] 保存失败: {e}")
            return Response(
                {"detail": "文件保存失败，请稍后重试"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        quota_rejected = _register_file_asset(request, FileAsset.Category.DOCUMENT, uploaded_file, file_path)
        if quota_rejected is not None:
            return quota_rejected

        return Response({
            "status": "success",
            "code": status.HTTP_201_CREATED,
            "message": "文件上传成功",
            "data": {
                # 统一返回相对 MEDIA_URL 的可访问地址，杜绝绝对路径泄露
                "file_path": relative_media_url(file_path),
                "file_name": uploaded_file.name,
                "file_size": uploaded_file.size,
            },
            "errors": None,
        }, status=status.HTTP_201_CREATED)


class ImageUploadView(APIView):
    """图片上传视图示例（含压缩和水印）"""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="图片上传",
        description="图片上传接口，自动压缩、添加文字水印并生成缩略图；含扩展名白名单校验。可选字段 watermark_text 自定义水印文案（默认项目名）。",
        tags=["文件上传"]
    )
    @validate_image_upload(
        file_field='image',
        max_file_size=settings.FILE_UPLOAD_MAX_FILE_SIZE,
        # 图片严格白名单
        allowed_extensions={'.jpg', '.jpeg', '.png', '.gif', '.webp'},
    )
    @handle_file_upload_exception
    def post(self, request):
        # 优雅处理：前端漏传图片时返回 400
        uploaded_file = request.FILES.get('image')
        if not uploaded_file:
            return Response(
                {"detail": "缺少文件字段: image"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            original_path = safe_file_upload(
                uploaded_file,
                upload_dir='images/original',
                random_filename=True
            )

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

            # 文字水印：默认项目名，前端可传 watermark_text 覆盖；位置/透明度用默认值
            watermark_text = (request.data.get('watermark_text') or settings.PROJECT_NAME)[:50]
            watermarked_path = processor.add_watermark(
                compressed_path,
                output_path=os.path.join(
                    settings.MEDIA_ROOT,
                    'images/watermarked',
                    os.path.basename(compressed_path)
                ),
                text=watermark_text,
                position='bottom-right',
            )

            thumbnail_path = processor.create_thumbnail(
                original_path,
                output_path=os.path.join(
                    settings.MEDIA_ROOT,
                    'images/thumbnails',
                    os.path.basename(original_path)
                ),
                size=(200, 200)
            )
        except (FileUploadError, OSError) as e:
            # 磁盘满 / 无写入权限 / 图片处理失败：服务端记录详情，前端返回安全提示
            logger.error(f"[ImageUpload] 处理失败: {e}")
            return Response(
                {"detail": "图片处理失败，请稍后重试"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 登记资产：一次上传=一条，登记原始上传；命中配额清理全部产物并 429
        quota_rejected = _register_file_asset(
            request, FileAsset.Category.IMAGE, uploaded_file,
            original_path, compressed_path, watermarked_path, thumbnail_path,
        )
        if quota_rejected is not None:
            return quota_rejected

        return Response({
            "status": "success",
            "code": status.HTTP_201_CREATED,
                "message": "图片上传成功",
                "data": {
                    # 统一相对 MEDIA_URL 地址；relative_media_url 已处理跨平台斜杠
                    "original": relative_media_url(original_path),
                    "compressed": relative_media_url(compressed_path),
                    "watermarked": relative_media_url(watermarked_path),
                    "thumbnail": relative_media_url(thumbnail_path),
                    "file_name": uploaded_file.name,
                    "file_size": uploaded_file.size,
                },
                "errors": None,
            }, status=status.HTTP_201_CREATED)


class TokenInfoView(APIView):
    """
    JWT access token 信息查询：解析 ``Authorization: Bearer`` 返回签发/过期时间、剩余有效秒数等，
    便于前端做「即将过期自动续期」或展示登录时长。
    需有效 Bearer token（IsAuthenticated）；免请求签名（SPA 直连场景同 upload 接口）。
    """

    authentication_classes = [SlidingJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="查询 access token 剩余有效时长",
        description=(
            "解析当前请求所携带的 access token，返回 exp/iat/剩余秒数等。"
            "需登录（IsAuthenticated）。"
        ),
        tags=["系统"],
    )
    def get(self, request):
        token = request.auth
        # SimpleJWT 的 AccessToken 对象提供 .payload；兜底直接 dict 化
        payload = token.payload if hasattr(token, "payload") else dict(token)

        def _to_ts(value):
            """exp/iat 可能是 int 时间戳（NumericDate）或 datetime，统一转成秒。"""
            if value is None:
                return None
            if isinstance(value, datetime):
                return value.timestamp()
            return float(value)

        now_ts = timezone.now().timestamp()
        exp_ts = _to_ts(payload.get("exp"))
        iat_ts = _to_ts(payload.get("iat"))
        remaining = int(exp_ts - now_ts) if exp_ts is not None else None

        data = {
            "token_type": "access",
            "user_id": payload.get("user_id"),
            "username": payload.get("username"),
            "iat": int(iat_ts) if iat_ts is not None else None,
            "exp": int(exp_ts) if exp_ts is not None else None,
            "exp_iso": (
                datetime.fromtimestamp(exp_ts, tz=dt_timezone.utc).isoformat()
                if exp_ts is not None else None
            ),
            "remaining_seconds": remaining,
            "expired": bool(remaining is not None and remaining <= 0),
        }
        return Response(data, status=status.HTTP_200_OK)


class VideoUploadView(APIView):
    """视频上传视图（视频类格式）"""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="视频上传",
        description="视频类文件上传接口，仅放行视频容器格式，享 100MB 放宽上限，含扩展名白名单校验",
        tags=["文件上传"]
    )
    @validate_file_upload(
        file_field='file',
        max_file_size=settings.FILE_UPLOAD_MAX_FILE_SIZE,
        # 视频类单独放宽：覆盖 validator 的默认视频上限（100MB）
        max_video_file_size=settings.FILE_UPLOAD_MAX_VIDEO_FILE_SIZE,
        # 仅放行视频类白名单（与全局 DEFAULT_VIDEO_EXTENSIONS 同步，自动跟随白名单维护）
        allowed_extensions=FileValidator.DEFAULT_VIDEO_EXTENSIONS,
    )
    @handle_file_upload_exception
    def post(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {"detail": "缺少文件字段: file"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            file_path = safe_file_upload(
                uploaded_file,
                upload_dir='videos',
                random_filename=True
            )
        except (FileUploadError, OSError) as e:
            # 磁盘满 / 无写入权限等底层错误：服务端记录详情，前端返回安全提示（不泄露路径）
            logger.error(f"[VideoUpload] 保存失败: {e}")
            return Response(
                {"detail": "视频保存失败，请稍后重试"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        quota_rejected = _register_file_asset(request, FileAsset.Category.VIDEO, uploaded_file, file_path)
        if quota_rejected is not None:
            return quota_rejected

        return Response({
            "status": "success",
            "code": status.HTTP_201_CREATED,
            "message": "视频上传成功",
            "data": {
                # 统一返回相对 MEDIA_URL 的可访问地址，杜绝绝对路径泄露
                "file_path": relative_media_url(file_path),
                "file_name": uploaded_file.name,
                "file_size": uploaded_file.size,
            },
            "errors": None,
        }, status=status.HTTP_201_CREATED)


class AudioUploadView(APIView):
    """音频上传视图（音频类格式）"""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="音频上传",
        description="音频类文件上传接口，仅放行音频格式，含大小限制与扩展名白名单校验",
        tags=["文件上传"]
    )
    @validate_file_upload(
        file_field='file',
        max_file_size=settings.FILE_UPLOAD_MAX_FILE_SIZE,
        # 仅放行音频类白名单（与全局 DEFAULT_AUDIO_EXTENSIONS 同步，自动跟随白名单维护）
        allowed_extensions=FileValidator.DEFAULT_AUDIO_EXTENSIONS,
    )
    @handle_file_upload_exception
    def post(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {"detail": "缺少文件字段: file"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            file_path = safe_file_upload(
                uploaded_file,
                upload_dir='audios',
                random_filename=True
            )
        except (FileUploadError, OSError) as e:
            # 磁盘满 / 无写入权限等底层错误：服务端记录详情，前端返回安全提示（不泄露路径）
            logger.error(f"[AudioUpload] 保存失败: {e}")
            return Response(
                {"detail": "音频保存失败，请稍后重试"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        quota_rejected = _register_file_asset(request, FileAsset.Category.AUDIO, uploaded_file, file_path)
        if quota_rejected is not None:
            return quota_rejected

        return Response({
            "status": "success",
            "code": status.HTTP_201_CREATED,
            "message": "音频上传成功",
            "data": {
                # 统一返回相对 MEDIA_URL 的可访问地址，杜绝绝对路径泄露
                "file_path": relative_media_url(file_path),
                "file_name": uploaded_file.name,
                "file_size": uploaded_file.size,
            },
            "errors": None,
        }, status=status.HTTP_201_CREATED)


# 文件资产管理（对齐 Fast-Vben-Admin file asset 管理页）
#   - FileAssetViewSet：读 file.view / 删+恢复 file.manage，软删不物理删文件
#   - FileAssetsUsageView：租户配额用量看板（复用 TenantProfileService.get_usage）


class FileAssetViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                       mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """文件资产管理：列表筛选（租户/分类/软删/关键词）+ 详情 + 软删 + 恢复（restore action）。
    资产仅由上传接口登记（无 create）；删除为软删（is_deleted=True），不物理删文件。
    """

    serializer_class = FileAssetSerializer
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']  # post 供 restore action 使用（无 create）

    def get_permissions(self):
        # 写操作（软删/恢复）需要 file.manage，读操作 file.view
        if self.action in ('destroy', 'restore'):
            return [permissions.IsAuthenticated(), FileManagePermission()]
        return [permissions.IsAuthenticated(), FileViewPermission()]

    def get_queryset(self):
        qs = FileAsset.objects.select_related('tenant', 'user').all()
        q = self.request.query_params
        tenant_id = q.get('tenant') or getattr(self.request, 'tenant_id', None)
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        category = q.get('category')
        if category:
            qs = qs.filter(category=category)
        deleted = q.get('deleted')  # '1'=仅已删 '0'=仅未删 不传=全部
        if deleted == '1':
            qs = qs.filter(is_deleted=True)
        elif deleted == '0':
            qs = qs.filter(is_deleted=False)
        keyword = (q.get('keyword') or '').strip()
        if keyword:
            from django.db.models import Q
            qs = qs.filter(Q(file_name__icontains=keyword) | Q(content_type__icontains=keyword))
        return qs

    def perform_destroy(self, instance):
        """软删：仅标记 is_deleted=True，不物理删除文件与登记记录（配额统计自动排除）。"""
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted', 'updated_at'])

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """软删恢复（file.manage）。"""
        asset = self.get_object()
        if not asset.is_deleted:
            return Response({"detail": "资产未处于删除状态", "code": "not_deleted"}, status=status.HTTP_400_BAD_REQUEST)
        asset.is_deleted = False
        asset.save(update_fields=['is_deleted', 'updated_at'])
        return Response(FileAssetSerializer(asset).data)


class FileAssetsUsageView(APIView):
    """租户配额用量看板（对齐 Vben 管理页）：?tenant=<id> 查指定租户，缺省=当前租户；需 file.view。"""

    permission_classes = [permissions.IsAuthenticated, FileViewPermission]

    def get(self, request):
        from rest_framework.exceptions import NotFound

        from system.saas.models import Tenant
        from system.saas.services import TenantProfileService

        tenant_id = request.query_params.get('tenant') or getattr(request, 'tenant_id', None)
        if not tenant_id:
            raise NotFound({"detail": "缺少租户上下文", "code": "tenant_required"})
        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant is None:
            raise NotFound({"detail": "租户不存在", "code": "tenant_not_found"})
        return Response(TenantProfileService.get_usage(tenant))


# 字典管理（对齐 Fast-Vben-Admin dictionaries.py）
# 语义：tenant=null 平台全局字典（所有租户可见），非空为租户私有；
#       公开读端点按 code 读取并缓存；管理端点读 dict.view / 写 dict.manage。

_DICT_CACHE_PREFIX = "dict:items:"
_DICT_CACHE_TTL = 3600


def _dict_cache_key(tenant_id, code: str) -> str:
    tid = str(tenant_id) if tenant_id else "global"
    return f"{_DICT_CACHE_PREFIX}{tid}:{code}"


def _invalidate_dict_cache(tenant_id, code: str) -> None:
    """写操作后删除对应缓存键（Redis 不可用时为 noop，天然降级）。"""
    try:
        from framework.cache.redis_client import get_redis
        get_redis().delete(_dict_cache_key(tenant_id, code))
    except Exception:
        pass


class DictTypeViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """字典类型 CRUD（管理端点：读 dict.view / 写 dict.manage）"""

    serializer_class = DictTypeSerializer

    def get_queryset(self):
        from django.db.models import Q

        from system.core.models import DictType
        from system.saas.permissions import _is_super_admin

        qs = DictType.objects.all()
        tenant = self._resolve_tenant(self.request)
        if tenant is not None:
            return qs.filter(Q(tenant=tenant) | Q(tenant__isnull=True))
        return qs if _is_super_admin(self.request.user) else qs.none()

    def get_permissions(self):
        from system.saas.permissions import DictManagePermission, DictViewPermission
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), DictManagePermission()]
        return [permissions.IsAuthenticated(), DictViewPermission()]

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied

        from system.saas.permissions import _is_super_admin

        tenant = self._resolve_tenant(self.request)
        if tenant is None and not _is_super_admin(self.request.user):
            raise PermissionDenied("无租户上下文，仅超级管理员可创建全局字典")
        obj = serializer.save(tenant=tenant)
        _invalidate_dict_cache(obj.tenant_id, obj.code)

    def perform_update(self, serializer):
        obj = serializer.save()
        _invalidate_dict_cache(obj.tenant_id, obj.code)

    def perform_destroy(self, instance):
        tenant_id = instance.tenant_id
        code = instance.code
        instance.delete()
        _invalidate_dict_cache(tenant_id, code)


class DictItemViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """字典项 CRUD（管理端点）"""

    serializer_class = DictItemSerializer

    def get_queryset(self):
        from django.db.models import Q

        from system.core.models import DictItem
        from system.saas.permissions import _is_super_admin

        qs = DictItem.objects.select_related('type')
        tenant = self._resolve_tenant(self.request)
        if tenant is not None:
            return qs.filter(Q(tenant=tenant) | Q(tenant__isnull=True))
        return qs if _is_super_admin(self.request.user) else qs.none()

    def get_permissions(self):
        from system.saas.permissions import DictManagePermission, DictViewPermission
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [permissions.IsAuthenticated(), DictManagePermission()]
        return [permissions.IsAuthenticated(), DictViewPermission()]

    def _resolve_type(self, type_id):
        """校验字典类型归属：当前租户或全局可见。"""
        from django.db.models import Q

        from system.core.models import DictType

        tenant = self._resolve_tenant(self.request)
        if tenant is not None:
            return DictType.objects.filter(
                Q(tenant=tenant) | Q(tenant__isnull=True), id=type_id).first()
        return DictType.objects.filter(id=type_id).first()

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        from system.saas.permissions import _is_super_admin

        tenant = self._resolve_tenant(self.request)
        if tenant is None and not _is_super_admin(self.request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("无租户上下文，仅超级管理员可创建字典项")
        type_obj = serializer.validated_data['type']
        if self._resolve_type(type_obj.id) is None:
            raise ValidationError({"type": "字典类型不存在或不属于当前租户"})
        obj = serializer.save(tenant=tenant)
        _invalidate_dict_cache(obj.tenant_id, type_obj.code)

    def perform_update(self, serializer):
        obj = serializer.save()
        _invalidate_dict_cache(obj.tenant_id, obj.type.code)

    def perform_destroy(self, instance):
        tenant_id = instance.tenant_id
        code = instance.type.code
        instance.delete()
        _invalidate_dict_cache(tenant_id, code)


class PublicDictItemsView(APIView):
    """按 code 读取字典项（登录即可，供前端下拉；带 Redis 缓存，写操作自动失效）"""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="按编码读取字典项",
        description="返回字典 code 下的启用项列表（含平台全局项 + 当前租户私有项），结果缓存 1 小时。",
        tags=['字典管理'],
        responses={200: OpenApiResponse(description="字典项列表")}
    )
    def get(self, request, code):
        import json

        from django.core.serializers.json import DjangoJSONEncoder
        from django.db.models import Q
        from rest_framework.exceptions import NotFound

        from framework.cache.redis_client import get_redis
        from system.core.models import DictItem, DictType

        tenant = TenantQuerysetMixin()._resolve_tenant(request)
        cache_key = _dict_cache_key(tenant.id if tenant else None, code)

        # 类型不存在或停用 → 404（与参考实现语义一致，避免空列表误导前端）
        type_qs = DictType.objects.filter(code=code, is_active=True)
        if tenant is not None:
            type_qs = type_qs.filter(Q(tenant=tenant) | Q(tenant__isnull=True))
        if not type_qs.exists():
            raise NotFound({"detail": "字典不存在", "code": "dict_not_found"})

        client = get_redis()
        try:
            cached = client.get(cache_key)
        except Exception:
            cached = None  # 缓存读失败降级直查库，不让缓存层打挂业务读
        if cached is not None:
            try:
                return Response(json.loads(cached))
            except (TypeError, ValueError):
                pass  # 缓存损坏 → 回源查库

        base = Q(type__code=code, type__is_active=True, is_active=True)
        if tenant is not None:
            items = DictItem.objects.filter(
                base & (Q(tenant=tenant) | Q(tenant__isnull=True)))
        else:
            items = DictItem.objects.filter(base & Q(tenant__isnull=True))
        items = items.select_related('type').order_by('sort', 'id')
        data = DictItemSerializer(items, many=True).data

        try:
            # DjangoJSONEncoder：dict 项含 UUID(id/type/tenant)，原生 json.dumps 会 TypeError
            client.set(cache_key, json.dumps(data, cls=DjangoJSONEncoder), ex=_DICT_CACHE_TTL)
        except Exception:
            pass  # 缓存写失败不影响读（降级为直查库）

        return Response(data)


# 平台级动态菜单（对齐 Fast-Vben-Admin 菜单/权限体系）
#   - MenuViewSet：平台级菜单树 CRUD（仅超级管理员维护）；
#   - MyMenusView：按角色权限码过滤下发菜单树 + 权限码集合（供前端 addRoute + v-permission 按钮级权限）。

def _user_permission_slugs(user) -> set[str] | None:
    """汇总用户全部权限码：租户成员角色（TenantMember→Role→Permission）+ 直接系统角色（user.role）；
    超管（is_superuser）返回 None 表示全量放行，免查库。"""
    if user.is_superuser:
        return None
    slugs: set[str] = set()
    from system.saas.models import TenantMember
    members = (
        TenantMember.objects
        .filter(user=user, is_active=True)
        .select_related('role')
    )
    for member in members:
        role = member.role
        if role and role.is_active:
            slugs.update(
                role.permissions.filter(is_active=True).values_list('slug', flat=True))
    user_role = getattr(user, 'role', None)
    if user_role and user_role.is_active:
        slugs.update(
            user_role.permissions.filter(is_active=True).values_list('slug', flat=True))
    return slugs


def _build_menu_tree(menus, slugs: set[str] | None, parent_id=None) -> list:
    """递归构建菜单树（按 sort 升序）。slugs 为 None（超管）→ 全部可见；
    节点绑定权限码且用户无 → 跳过（子树随之整体丢弃）；权限码为空 → 登录即可见；
    过滤后的子树挂实例 ``_children``，MenuSerializer 优先渲染。"""
    tree = []
    for m in menus:
        if m.parent_id != parent_id:
            continue
        if slugs is not None and m.permission and m.permission not in slugs:
            continue
        m._children = _build_menu_tree(menus, slugs, parent_id=m.id)
        tree.append(m)
    return tree


class MenuViewSet(viewsets.ModelViewSet):
    """平台级菜单 CRUD（仅超级管理员）。管理端看全量（含停用项便于恢复），my-menus 另做 is_active/is_visible 过滤；
    树形经 parent 表达；按钮节点必须绑定权限码（序列化器校验）。"""

    queryset = Menu.objects.all()
    serializer_class = MenuSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    @extend_schema(
        summary="菜单树列表（平台级）",
        description="仅超级管理员可见；返回全部菜单节点（含停用），children 递归展开。",
        tags=["菜单管理"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="创建菜单节点",
        description="按钮类型（type=button）必须绑定 permission 权限码。",
        tags=["菜单管理"],
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)


class MyMenusView(APIView):
    """当前用户可见菜单树 + 权限码集合。
    超管 → 全量菜单 + Permission 表全部 slug；普通用户 → permission 为空（登录可见）或命中其权限码才下发，
    父节点不可见时子树整体丢弃（避免孤立路由）。返回 {"menus": 树, "permissions": [slug...]}。
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="我的菜单（动态路由 + 按钮级权限）",
        description="返回按当前用户角色权限码过滤后的菜单树与权限码集合，供前端 addRoute / v-permission 使用。",
        tags=["菜单管理"],
    )
    def get(self, request):
        user = request.user
        menus = list(
            Menu.objects
            .filter(is_active=True, is_visible=True)
            .order_by('sort', 'created_at')
        )
        slugs = _user_permission_slugs(user)
        tree = _build_menu_tree(menus, slugs)

        if slugs is None:
            from system.saas.models import Permission
            permissions = list(
                Permission.objects.filter(is_active=True).values_list('slug', flat=True))
        else:
            permissions = sorted(slugs)

        return Response({
            "menus": MenuSerializer(tree, many=True).data,
            "permissions": permissions,
        })
