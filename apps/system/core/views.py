from django.http import HttpResponse
from loguru import logger
from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from framework.drf.renderer import CustomRenderer
from framework.drf.timed_api_key_auth import TimedAPIKeyAuthentication
from framework.drf.sliding_jwt import SlidingJWTAuthentication
from rest_framework import permissions
from django.conf import settings
import os
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets, mixins
from rest_framework.decorators import action

from framework.helpers.system_config import get_system_info
from framework.helpers.time_utils import nowtime
from framework.cache.view_cache import drf_cache_view, T_5_MINUTES
from .models import AuditLog, APIKey
from .serializers import (
    AuditLogSerializer, PingSerializer, CreateApiKeySerializer, ApiKeySerializer,
)
from .permissions import CanIssueApiKey, CanManageApiKey
from .health import HealthChecker

from framework.files.upload import safe_file_upload, FileValidator, FileUploadError, relative_media_url
from framework.files.upload.image_processor import ImageProcessor
from framework.helpers.decorators import validate_file_upload, validate_image_upload, handle_file_upload_exception

from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone

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


class PingAuthView(APIView):
    """
    对照演示：把 authentication_classes 换成 JWT 后端后，请求如何被识别。

    关键点：
    - 与 PingView 一样用 permission_classes=[AllowAny]，所以「未带 token」也能 200；
    - 但 authentication_classes=[SlidingJWTAuthentication] 后，DRF 会尝试解析
      Authorization: Bearer <token>；带【有效】token 时 request.user 被填充为对应用户，
      request.auth 为 token 对象；带【无效/过期】token 时由认证层直接 401 拒绝；
      完全【不带】token 时则匿名通过（认证失败≠禁止，禁止由 permission_classes 决定）。
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
    受「时效性密钥」保护的接口示例。

    请求必须携带**有效且未过期**的 API Key（X-API-Key 或 Authorization: Bearer）。
    密钥的「正确性」与「时效性」由 TimedAPIKeyAuthentication 在视图执行前**同步**校验：
    缺失 / 错误 / 禁用 / 过期 任一不满足都直接返回 401，绝不进入本方法返回受保护信息。

    验证通过后才执行 get()，返回仅持有效密钥可见的数据，并附带密钥的时效信息。
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
    API Key 生命周期管理视图集（挂在 /api/ 路由下）。

    路由：
      POST   /api/api-keys/              签发（仅管理员，JWT 鉴权）
      GET    /api/api-keys/              列表（管理员看全部，普通用户仅看自己名下）
      GET    /api/api-keys/{pk}/         详情（脱敏）
      PATCH  /api/api-keys/{pk}/         改名 / 吊销(is_active=false) / 重新启用
      DELETE /api/api-keys/{pk}/         删除（吊销且从库移除）
      POST   /api/api-keys/{pk}/rotate/  轮换（作废旧密钥，签发新密钥）

    安全约定：
      - 管理接口一律要求真实 JWT（SlidingJWTAuthentication），禁止用 API Key 自身管理，
        防止凭证链式放大；
      - 明文密钥仅在签发 / 轮换时一次性返回；列表与详情使用 masked_key 脱敏，
        绝不回显明文 key 字段；
      - 普通用户仅能操作自己名下的密钥（CanManageApiKey 对象级校验）；
      - 签发(create) 单独由 CanIssueApiKey 管控（仅管理员）。
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

    # ------------------------------------------------------------------ #
    # 签发（仅管理员）
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # 轮换（作废旧密钥，签发新密钥）
    # ------------------------------------------------------------------ #
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
        # 作废旧密钥
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

    # ------------------------------------------------------------------ #
    # 部分更新（改名 / 吊销 / 重新启用）
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # 删除（吊销且移除）
    # ------------------------------------------------------------------ #
    def perform_destroy(self, instance):
        self._audit(self.request, instance, "DELETE", "SENSITIVE", {
            "action": "delete",
            "id": str(instance.id),
            "name": instance.name,
            "operator": self.request.user.username,
        })
        instance.delete()

    # ------------------------------------------------------------------ #
    # 审计辅助
    # ------------------------------------------------------------------ #
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


class DocumentUploadView(APIView):
    """
    文档上传视图（文档 / 数据 / 归档 / 字体等）
    """
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
                {'detail': '缺少文件字段: file'},
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
                {'detail': '文件保存失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'code': status.HTTP_201_CREATED,
            'message': '文件上传成功',
            'data': {
                # 统一返回相对 MEDIA_URL 的可访问地址，杜绝绝对路径泄露
                'file_path': relative_media_url(file_path),
                'file_name': uploaded_file.name,
                'file_size': uploaded_file.size,
            },
            'errors': None,
        }, status=status.HTTP_201_CREATED)


class ImageUploadView(APIView):
    """
    图片上传视图示例（含压缩和水印）
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="图片上传",
        description="图片上传接口，自动压缩并添加水印，含扩展名白名单校验",
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
                {'detail': '缺少文件字段: image'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
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
        except (FileUploadError, OSError) as e:
            # 磁盘满 / 无写入权限 / 图片处理失败：服务端记录详情，前端返回安全提示
            logger.error(f"[ImageUpload] 处理失败: {e}")
            return Response(
                {'detail': '图片处理失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'code': status.HTTP_201_CREATED,
                'message': '图片上传成功',
                'data': {
                    # 统一相对 MEDIA_URL 地址；relative_media_url 已处理跨平台斜杠
                    'original': relative_media_url(original_path),
                    'compressed': relative_media_url(compressed_path),
                    'thumbnail': relative_media_url(thumbnail_path),
                    'file_name': uploaded_file.name,
                    'file_size': uploaded_file.size,
                },
                'errors': None,
            }, status=status.HTTP_201_CREATED)


class TokenInfoView(APIView):
    """
    JWT access token 信息查询接口。

    从当前请求的 ``Authorization: Bearer`` 解析 JWT，返回签发/过期时间、剩余有效秒数等，
    便于前端做「即将过期自动续期」或展示登录剩余时长。
    需携带有效 Bearer token（IsAuthenticated）；免请求签名（SPA 直连场景同 upload 接口）。
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
    """
    视频上传视图（视频类格式）
    """
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
                {'detail': '缺少文件字段: file'},
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
                {'detail': '视频保存失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'code': status.HTTP_201_CREATED,
            'message': '视频上传成功',
            'data': {
                # 统一返回相对 MEDIA_URL 的可访问地址，杜绝绝对路径泄露
                'file_path': relative_media_url(file_path),
                'file_name': uploaded_file.name,
                'file_size': uploaded_file.size,
            },
            'errors': None,
        }, status=status.HTTP_201_CREATED)


class AudioUploadView(APIView):
    """
    音频上传视图（音频类格式）
    """
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
                {'detail': '缺少文件字段: file'},
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
                {'detail': '音频保存失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'status': 'success',
            'code': status.HTTP_201_CREATED,
            'message': '音频上传成功',
            'data': {
                # 统一返回相对 MEDIA_URL 的可访问地址，杜绝绝对路径泄露
                'file_path': relative_media_url(file_path),
                'file_name': uploaded_file.name,
                'file_size': uploaded_file.size,
            },
            'errors': None,
        }, status=status.HTTP_201_CREATED)
