"""用户域视图层。

承载用户注册、登录/登出、令牌签发与刷新、用户信息、用户管理（CRUD）、MFA 状态
与设置等 API 视图。登录统一走 CustomTokenObtainPairView 以叠加 token_version
即时失效、登录日志落库等安全机制。
"""

from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    UserRegisterSerializer, UserDetailSerializer, UserLoginSerializer, TestApiSerializer,
    CustomTokenObtainPairSerializer, RefreshTokenSerializer, LogoutSerializer, UserManageSerializer,
    UserManageSerializerV2,
    MfaSetupSerializer, MfaConfirmSerializer, MfaDisableSerializer, MfaRecoverySerializer,
)
from .permissions import IsAdminOrSelf, DataPermissionMixin
from loguru import logger
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes

# 租户级登录日志（显式落库，避免信号双写）
from system.core.audit import record_login_log
# 登录限流（IP+用户名双维度，防暴力破解；Redis 故障自动放行）
from framework.gateway.login_throttle import LoginThrottleService

User = get_user_model()

class TestApiView(generics.GenericAPIView):
    """规范化测试接口：演示 Swagger 规范与项目自动发现机制的写法。
    注意：用 get_serializer()/serializer_class 需 GenericAPIView 基类
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TestApiSerializer

    @extend_schema(
        summary="发送测试消息",
        description="该接口用于测试系统的规范化写法，支持 GET 传参和 POST 提交 JSON。",
        parameters=[
            OpenApiParameter(name='type', description='测试类型', required=False, type=OpenApiTypes.STR),
        ],
        responses={
            200: TestApiSerializer,
            401: OpenApiResponse(description="未授权访问")
        },
        tags=['测试模块']
    )
    def get(self, request):
        test_type = request.query_params.get('type', 'default')
        data = {
            "msg": f"GET 请求成功，类型为: {test_type}",
            "status": True
        }
        serializer = self.get_serializer(data)
        return Response(serializer.data)

    @extend_schema(
        summary="提交测试数据",
        request=TestApiSerializer,
        responses={201: TestApiSerializer},
        tags=['测试模块']
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class UserRegisterView(generics.CreateAPIView):
    """用户注册视图 (API)"""
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = serializer.save()
        logger.info(f"新用户注册: {user.username}")

    def create(self, request, *args, **kwargs):
        # 注册限流预检：IP 窗口超限→429；语义同登录限流（fail-open：Redis 故障不阻断）
        from framework.gateway.login_throttle import LoginThrottleService

        if LoginThrottleService.is_register_rate_limited(request):
            logger.warning("注册失败: 触发注册限流 - [{}]", request.data.get('username'))
            return Response({"detail": _("注册过于频繁，请稍后再试")},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("注册失败: 用户输入无效 - {}", serializer.errors)
            # 校验失败也计数（防垃圾数据试探）
            LoginThrottleService.record_register_attempt(request)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # 用户创建 + Outbox user.created 事件同事务提交（业务成功事件必不丢，失败一并回滚）
        from django.db import transaction
        from framework.events.publisher import publish
        from framework.log_utils.request_id import get_request_id
        from system.users.events import USER_CREATED

        with transaction.atomic():
            self.perform_create(serializer)
            publish(USER_CREATED, {
                "user_id": serializer.instance.pk,
                "username": serializer.validated_data['username'],
                "email": serializer.validated_data.get('email') or '',
                "nickname": serializer.validated_data.get('nickname') or '',
            }, trace_id=get_request_id())

        # 成功注册同样计数（消耗窗口额度，防批量开号；不清零，锁随窗口过期解除）
        LoginThrottleService.record_register_attempt(request)

        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
        logger.success(f"新用户注册成功: 用户名=[{serializer.validated_data['username']}], IP=[{ip}]")

        return Response(serializer.data, status=status.HTTP_201_CREATED)

from django.utils import timezone
from datetime import timedelta
from django.conf import settings

class UserLoginView(APIView):
    """用户登录视图 (返回 JWT Token)"""
    permission_classes = [permissions.AllowAny]
    serializer_class = UserLoginSerializer

    @extend_schema(
        summary="用户登录",
        description="用户身份验证，成功后返回 JWT Token。",
        request=UserLoginSerializer,
        responses={
            200: OpenApiResponse(description="登录成功，返回 Token"),
            401: OpenApiResponse(description="用户名或密码错误"),
            403: OpenApiResponse(description="账号已被禁用"),
        }
    )
    def post(self, request):
        # 限流预检：IP/用户名任一维度锁定→429（防暴力破解）
        raw_username = request.data.get('username') or ''
        if LoginThrottleService.is_login_rate_limited(request, raw_username):
            logger.warning(f"登录失败: 触发登录限流 - [{raw_username}]")
            record_login_log(
                email=raw_username, status='failed', request=request,
                failure_reason='rate_limited',
            )
            return Response({"detail": _("尝试过于频繁，请稍后再试")},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        serializer = UserLoginSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("登录失败: 数据验证不通过 - {}", serializer.errors)
            LoginThrottleService.record_failed_login_attempt(request, raw_username)
            record_login_log(
                email=request.data.get('username') or '',
                status='failed', request=request, failure_reason='invalid_data',
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        # 禁用预检：is_active=False 在 authenticate() 阶段被 ModelBackend 短路，
        # 须提前拦截，否则禁用账号落 401(bad_credentials) 而非 403，403 分支成死代码
        if User.objects.filter(username=username, is_active=False).exists():
            logger.warning(f"登录失败: 账号已被禁用 - [{username}]")
            LoginThrottleService.record_failed_login_attempt(request, username)
            record_login_log(email=username, status='failed', request=request,
                             failure_reason='disabled')
            return Response({"detail": _("该账号已被禁用")}, status=status.HTTP_403_FORBIDDEN)

        # 统一认证，不区分不存在/密码错（防用户名枚举）
        user = authenticate(username=username, password=password)

        if user:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

            # MFA 校验：启用 MFA 须携带 mfa_code（TOTP/恢复码）；失败计入限流
            from system.users.services import verify_mfa_for_login
            mfa_ok, mfa_reason = verify_mfa_for_login(user, request.data.get('mfa_code'))
            if not mfa_ok:
                logger.warning(f"登录失败: MFA 校验{mfa_reason} - [{username}]")
                LoginThrottleService.record_failed_login_attempt(request, username)
                record_login_log(email=username, status='failed', request=request,
                                 failure_reason='mfa_failed')
                if mfa_reason == 'mfa_required':
                    # detail+code 结构经 CustomRenderer 落入 errors.error_code，前端可精确判断
                    return Response({"detail": _("需要二次验证"), "code": "mfa_required"},
                                    status=status.HTTP_400_BAD_REQUEST)
                return Response({"detail": _("二次验证失败"), "code": "mfa_failed"},
                                status=status.HTTP_401_UNAUTHORIZED)

            logger.success(f"用户登录成功: 用户名=[{user.username}], 角色=[{getattr(user, 'role', 'user')}], IP=[{ip}]")

            # 令牌版本戳：每次登录自增并写入 claim，使该用户所有旧 token 立即失效
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)

            if hasattr(user, "token_version"):
                user.token_version = (user.token_version or 0) + 1
                user.save(update_fields=["token_version"])
                refresh["token_version"] = user.token_version

            # 注入多租户 claim + 会话记录（对齐 LoginService.login；
            # 此前不建会话→登出/会话管理管不到该 token，此处补齐）
            from system.users.serializers import attach_tenant_claim, create_user_session
            tenant_id = attach_tenant_claim(refresh, request, user)
            # 先取 access 实例复用（属性每次访问生成新 jti）
            access = refresh.access_token
            create_user_session(user, access, tenant_id, request, notify_new_device=True)

            record_login_log(
                email=user.email or user.username, status='success',
                user=user, tenant_id=tenant_id, request=request,
            )

            # 成功清零 IP/用户名双维度计数
            LoginThrottleService.clear_failed_login_attempts(request, username)

            return Response({
                "refresh": str(refresh),
                "access": str(access),
                "user": {
                    "id": user.pk,
                    "username": user.username,
                    "email": user.email,
                    "nickname": getattr(user, "nickname", ""),
                    "role": (user.role.name if user.role else None),
                    "tenant_id": tenant_id,
                }
            })

        # 统一返回用户名或密码错误（防枚举）
        logger.warning(f"登录失败: 用户名或密码错误 - [{username}]")
        LoginThrottleService.record_failed_login_attempt(request, username)
        record_login_log(email=username, status='failed', request=request,
                         failure_reason='bad_credentials')
        return Response({"detail": _("用户名或密码错误")}, status=status.HTTP_401_UNAUTHORIZED)

class UserLogoutView(APIView):
    """用户登出视图 - 支持 JWT 黑名单和 Session 清理"""
    permission_classes = [permissions.AllowAny]  # 允许未认证，避免 401

    @extend_schema(
        summary="用户登出",
        description="退出登录，支持 JWT Token 黑名单和 Session 清理。",
        request=LogoutSerializer,
        responses={200: OpenApiResponse(description="登出成功")}
    )
    def post(self, request):
        try:
            # 统一走 LogoutService：会话吊销+API Token+Session 退出+JWT 黑名单
            from .services import LogoutService

            LogoutService.logout(
                request, refresh_token=request.data.get('refresh')
            )
            return Response({"message": _("登出成功")}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"用户登出异常: {e}")
            return Response({"detail": _("登出失败")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserInfoView(generics.RetrieveUpdateAPIView):
    """用户信息查看和修改"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSelf]

    def get_object(self):
        # 传了 pk 则取指定用户（受 IsAdminOrSelf 保护）
        pk = self.kwargs.get('pk')
        if pk:
            return super().get_object()
        # 否则返回当前登录用户
        return self.request.user

from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from djangoProjectTest.pagination import StandardPagination
from rest_framework import viewsets


class UserListView(DataPermissionMixin, generics.ListAPIView):
    """
    用户列表（受数据权限控制）：管理员看全量，普通用户仅看自己。
    支持：按 role 过滤；username/nickname/mobile 模糊搜索；按 id/date_joined 排序；每页 20 条（page/page_size）。
    """
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['role']
    search_fields = ['username', 'nickname', 'mobile']
    ordering_fields = ['id', 'date_joined']
    ordering = ['-id']

# JWT 认证视图

class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT 登录视图 - 获取 Token 对"""
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    
    @extend_schema(
        summary="JWT 登录",
        description="使用用户名和密码获取 JWT Token",
        tags=['认证'],
        responses={200: OpenApiResponse(description="登录成功，返回 access 和 refresh token")}
    )
    def post(self, request, *args, **kwargs):
        # 限流预检：IP/用户名任一维度锁定→429（防暴力破解）
        raw_username = request.data.get('username') or ''
        if LoginThrottleService.is_login_rate_limited(request, raw_username):
            logger.warning(f"JWT登录失败: 触发登录限流 - [{raw_username}]")
            from system.core.audit import record_login_log
            record_login_log(email=raw_username, status='failed', request=request,
                             failure_reason='rate_limited')
            return Response({"detail": _("尝试过于频繁，请稍后再试")},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        response = super().post(request, *args, **kwargs)
        
        username = request.data.get('username')
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
        logger.success(f"JWT登录成功: 用户名=[{username}], IP=[{ip}]")
        
        return response

class CustomTokenRefreshView(TokenRefreshView):
    """JWT 刷新 Token 视图"""
    serializer_class = RefreshTokenSerializer
    permission_classes = [permissions.AllowAny]
    
    @extend_schema(
        summary="刷新 JWT Token",
        description="使用 refresh token 获取新的 access token",
        tags=['认证'],
        responses={200: OpenApiResponse(description="刷新成功，返回新的 access token")}
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

class JWTLogoutView(APIView):
    """JWT 登出视图 - 将 refresh token 加入黑名单"""
    permission_classes = [permissions.AllowAny]  # 允许未认证，避免 401
    serializer_class = LogoutSerializer
    
    @extend_schema(
        summary="JWT 登出",
        description="将 refresh token 加入黑名单，使其失效",
        tags=['认证'],
        responses={200: OpenApiResponse(description="登出成功")}
    )
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response({"detail": "缺少 refresh token"}, status=status.HTTP_400_BAD_REQUEST)

            # 统一走 LogoutService：会话吊销+API Token+Session 退出+JWT 黑名单
            from .services import LogoutService

            LogoutService.logout(request, refresh_token=refresh_token)
            return Response({"message": "登出成功"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"JWT登出失败: {e}")
            return Response({"detail": "登出失败"}, status=status.HTTP_400_BAD_REQUEST)

class SystemRoleListView(APIView):
    """获取系统角色列表（tenant=null）；无系统角色时自动调用 init_permissions 初始化"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="获取系统角色列表",
        description="获取所有 tenant=null 的系统角色",
        tags=['用户管理']
    )
    def get(self, request):
        Role = apps.get_model('saas', 'Role')

        # 无系统角色则告警（初始化应在部署脚本执行）
        if not Role.objects.filter(tenant__isnull=True).exists():
            logger.warning('系统角色未初始化，请运行: python manage.py init_permissions')

        roles = Role.objects.filter(tenant__isnull=True, is_active=True)
        role_data = []
        for role in roles:
            role_data.append({
                'id': str(role.id),
                'name': role.name,
                'slug': role.slug,
                'description': role.description,
                'is_system': role.is_system,
                'is_active': role.is_active
            })
        return Response(role_data)


class VerifyTokenView(APIView):
    """验证 Token 有效性"""
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="验证 Token",
        description="验证当前 Token 是否有效，并返回用户信息",
        tags=['认证'],
        responses={200: OpenApiResponse(description="Token 有效")}
    )
    def get(self, request):
        return Response({
            "valid": True,
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "email": request.user.email,
                "role_id": str(request.user.role.id) if request.user.role else None,
                "role_name": request.user.role.name if request.user.role else None,
            }
        })


# 用户管理 ViewSet

class UserManageViewSet(viewsets.ModelViewSet):
    """系统用户管理 ViewSet（CRUD）：管理员可创建/查看/编辑/删除用户、管理角色；仅系统管理员可访问"""
    queryset = User.objects.select_related('role').all()
    serializer_class = UserManageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['role', 'is_active']
    search_fields = ['username', 'email', 'nickname', 'mobile']
    ordering_fields = ['id', 'date_joined', 'username']
    ordering = ['-date_joined']

    def get_queryset(self):
        user = self.request.user
        from system.saas.permissions import _is_super_admin
        is_super = _is_super_admin(user)
        
        if not is_super:
            # 普通用户仅看自己
            return User.objects.filter(id=user.id)
        
        return User.objects.select_related('role').all()

    def perform_destroy(self, instance):
        # 不能删除自己
        if instance == self.request.user:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("不能删除自己的账号")
        instance.delete()

    def get_permissions(self):
        """SaaS RBAC 权限：写入操作（create/update/partial_update/destroy）需 user.manage，list 需 user.view，超管自动放行"""
        from system.saas.permissions import UserManagePermission, UserViewPermission
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), UserManagePermission()]
        if self.action == 'list':
            return [permissions.IsAuthenticated(), UserViewPermission()]
        # retrieve：已登录即可（详情通过其他端点）
        return [permissions.IsAuthenticated()]


class UserManageViewSetV2(UserManageViewSet):
    """用户管理 v2 ViewSet：继承 v1，仅切换 serializer_class 到 v2（增加 version 字段），其余逻辑复用 v1"""
    serializer_class = UserManageSerializerV2


# MFA 双因子认证视图（对齐 Fast-Vben-Admin core/mfa.py）：status→setup→confirm→登录携带 mfa_code；disable/recovery 需验证

class MfaStatusView(APIView):
    """查询当前用户 MFA 状态"""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="MFA 状态查询",
        description="返回当前用户 MFA 启用状态、确认时间与剩余恢复码数量。",
        tags=['MFA 双因子认证'],
        responses={200: OpenApiResponse(description="MFA 状态")}
    )
    def get(self, request):
        from .services import MfaService
        return Response(MfaService.status(request.user))


class MfaSetupView(APIView):
    """生成 MFA 绑定（新 secret + 恢复码，pending 态待 confirm 启用）"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MfaSetupSerializer

    @extend_schema(
        summary="MFA 绑定生成",
        description="生成 TOTP secret / otpauth URI / 恢复码明文（仅此一次展示）。"
                    "已启用 MFA 的用户须携带当前 mfa_code（TOTP 或恢复码）防劫持换绑。",
        request=MfaSetupSerializer,
        tags=['MFA 双因子认证'],
        responses={200: OpenApiResponse(description="绑定信息（secret/uri/recovery_codes）")}
    )
    def post(self, request):
        from rest_framework.exceptions import ValidationError
        from .services import MfaService

        serializer = MfaSetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = MfaService.setup(
                request.user, mfa_code=serializer.validated_data.get('mfa_code'))
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)


class MfaConfirmView(APIView):
    """确认绑定并启用 MFA（提交 Authenticator 6 位 TOTP 码）"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MfaConfirmSerializer

    @extend_schema(
        summary="MFA 绑定确认",
        description="提交 6 位 TOTP 验证码完成绑定，成功后 mfa_enabled=True。",
        request=MfaConfirmSerializer,
        tags=['MFA 双因子认证'],
        responses={200: OpenApiResponse(description="启用成功"), 400: OpenApiResponse(description="验证码错误")}
    )
    def post(self, request):
        from rest_framework.exceptions import ValidationError
        from .services import MfaService

        serializer = MfaConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = MfaService.confirm(request.user, serializer.validated_data['code'])
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)


class MfaDisableView(APIView):
    """禁用 MFA（TOTP 或恢复码任一验证通过）"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MfaDisableSerializer

    @extend_schema(
        summary="MFA 禁用",
        description="提交 TOTP 6 位验证码或恢复码验证通过后，清空全部 MFA 字段。",
        request=MfaDisableSerializer,
        tags=['MFA 双因子认证'],
        responses={200: OpenApiResponse(description="禁用成功"), 400: OpenApiResponse(description="验证失败")}
    )
    def post(self, request):
        from rest_framework.exceptions import ValidationError
        from .services import MfaService

        serializer = MfaDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = MfaService.disable(request.user, serializer.validated_data['code'])
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)


class MfaRecoveryView(APIView):
    """重新生成恢复码（TOTP 验证，旧恢复码作废）"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MfaRecoverySerializer

    @extend_schema(
        summary="MFA 恢复码重新生成",
        description="提交 6 位 TOTP 验证码确认持有 Authenticator 后，重新生成恢复码（旧码作废）。",
        request=MfaRecoverySerializer,
        tags=['MFA 双因子认证'],
        responses={200: OpenApiResponse(description="新恢复码列表"), 400: OpenApiResponse(description="验证失败")}
    )
    def post(self, request):
        from rest_framework.exceptions import ValidationError
        from .services import MfaService

        serializer = MfaRecoverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = MfaService.regenerate_recovery_codes(
                request.user, serializer.validated_data['code'])
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)

