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
    UserManageSerializerV2
)
from .permissions import IsAdminOrSelf, DataPermissionMixin
from loguru import logger
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes

User = get_user_model()

class TestApiView(generics.GenericAPIView):
    """
    规范化测试接口

    演示如何编写一个符合 Swagger 规范和项目自动发现机制的接口。
    包括请求参数说明、序列化器关联以及响应示例。

    注意：使用 get_serializer()/serializer_class 需要 GenericAPIView 基类
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
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"注册失败: 用户输入无效 - {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self.perform_create(serializer)

        # 获取请求 IP
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
        serializer = UserLoginSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"登录失败: 数据验证不通过 - {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        # 统一认证，不区分"账号不存在"和"密码错误"（防止用户名枚举）
        user = authenticate(username=username, password=password)

        if user:
            if not user.is_active:
                logger.warning(f"登录失败: 账号已被禁用 - [{username}]")
                return Response({'detail': _('该账号已被禁用')}, status=status.HTTP_403_FORBIDDEN)

            # 获取请求 IP
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

            logger.success(f"用户登录成功: 用户名=[{user.username}], 角色=[{getattr(user, 'role', 'user')}], IP=[{ip}]")

            # 使用 JWT 认证生成 token
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)

            # 注入多租户上下文 claim（tenant_id）
            from system.users.serializers import resolve_login_tenant
            tenant_id = resolve_login_tenant(request, user)
            if tenant_id:
                refresh['tenant_id'] = tenant_id

            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': {
                    'id': user.pk,
                    'username': user.username,
                    'email': user.email,
                    'nickname': getattr(user, 'nickname', ''),
                    'role': (user.role.name if user.role else None),
                    'tenant_id': tenant_id,
                }
            })

        # 统一返回用户名或密码错误（不区分账号不存在/密码错误，防止枚举）
        logger.warning(f"登录失败: 用户名或密码错误 - [{username}]")
        return Response({'detail': _('用户名或密码错误')}, status=status.HTTP_401_UNAUTHORIZED)

class UserLogoutView(APIView):
    """用户登出视图 - 支持 JWT 黑名单和 Session 清理"""
    permission_classes = [permissions.AllowAny]  # 允许未认证访问，避免 401

    @extend_schema(
        summary="用户登出",
        description="退出登录，支持 JWT Token 黑名单和 Session 清理。",
        request=LogoutSerializer,
        responses={200: OpenApiResponse(description="登出成功")}
    )
    def post(self, request):
        try:
            username = None

            # 1. 如果是已认证用户，先获取用户名用于日志
            if request.user and request.user.is_authenticated:
                username = request.user.username

                # 1.1 退出 Session 登录
                from django.contrib.auth import logout
                logout(request)

            # 2. 处理 JWT 登出 - 将 refresh token 加入黑名单
            refresh_token = request.data.get('refresh')
            if refresh_token:
                try:
                    from rest_framework_simplejwt.tokens import RefreshToken
                    token = RefreshToken(refresh_token)
                    token.blacklist()
                    logger.info("JWT Token 已加入黑名单")
                except Exception as e:
                    logger.warning(f"JWT Token 黑名单处理失败: {e}")

            if username:
                logger.info(f"用户登出成功: {username}")
            else:
                logger.info("匿名用户登出请求")

            return Response({'message': _('登出成功')}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"用户登出异常: {e}")
            return Response({'detail': _('登出失败')}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserInfoView(generics.RetrieveUpdateAPIView):
    """用户信息查看和修改"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSelf]

    def get_object(self):
        # 如果 URL 中传了 pk，则获取指定用户（受 IsAdminOrSelf 保护）
        pk = self.kwargs.get('pk')
        if pk:
            return super().get_object()
        # 否则默认返回当前登录用户
        return self.request.user

from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from djangoProjectTest.pagination import StandardPagination
from rest_framework import viewsets


class UserListView(DataPermissionMixin, generics.ListAPIView):
    """
    ### 用户列表接口说明
    
    **功能描述**：获取系统用户列表（受数据权限控制）。
    
    **权限说明**：
    - 管理员：可以查看全量用户。
    - 普通用户：仅能看到自己的信息。

    **支持的操作**：
    - **过滤**：支持按 `role` 过滤。
    - **搜索**：支持按 `username`, `nickname`, `mobile` 进行模糊搜索。
    - **排序**：支持按 `id`, `date_joined` 排序。
    - **分页**：默认每页 20 条，支持 `page` 和 `page_size` 参数。
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

# =====================================================
# JWT 认证视图
# =====================================================

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    JWT 登录视图 - 获取 Token 对
    """
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    
    @extend_schema(
        summary="JWT 登录",
        description="使用用户名和密码获取 JWT Token",
        tags=['认证'],
        responses={200: OpenApiResponse(description="登录成功，返回 access 和 refresh token")}
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        # 记录登录日志
        username = request.data.get('username')
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
        logger.success(f"JWT登录成功: 用户名=[{username}], IP=[{ip}]")
        
        return response

class CustomTokenRefreshView(TokenRefreshView):
    """
    JWT 刷新 Token 视图
    """
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
    """
    JWT 登出视图 - 将 refresh token 加入黑名单
    """
    permission_classes = [permissions.AllowAny]  # 允许未认证访问，避免 401
    serializer_class = LogoutSerializer
    
    @extend_schema(
        summary="JWT 登出",
        description="将 refresh token 加入黑名单，使其失效",
        tags=['认证'],
        responses={200: OpenApiResponse(description="登出成功")}
    )
    def post(self, request):
        try:
            username = None

            # 1. 如果是已认证用户，清理 Session 登录
            if request.user and request.user.is_authenticated:
                username = request.user.username

                # 退出 Session 登录
                from django.contrib.auth import logout
                logout(request)

            # 2. 处理 JWT 登出 - 将 refresh token 加入黑名单
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response({'detail': '缺少 refresh token'}, status=status.HTTP_400_BAD_REQUEST)
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            logger.info("JWT Token 已加入黑名单")
            
            if username:
                logger.info(f"JWT登出成功: 用户=[{username}]")
            else:
                logger.info("JWT登出成功（匿名用户）")
            
            return Response({'message': '登出成功'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"JWT登出失败: {e}")
            return Response({'detail': '登出失败'}, status=status.HTTP_400_BAD_REQUEST)

class SystemRoleListView(APIView):
    """
    获取系统角色列表（tenant=null 的角色）
    如果没有任何系统角色，会自动调用 init_permissions 命令初始化
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="获取系统角色列表",
        description="获取所有 tenant=null 的系统角色",
        tags=['用户管理']
    )
    def get(self, request):
        Role = apps.get_model('saas', 'Role')

        # 如果没有任何系统角色，返回空列表（初始化应在部署脚本中执行）
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
    """
    验证 Token 有效性
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="验证 Token",
        description="验证当前 Token 是否有效，并返回用户信息",
        tags=['认证'],
        responses={200: OpenApiResponse(description="Token 有效")}
    )
    def get(self, request):
        return Response({
            'valid': True,
            'user': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
                'role_id': str(request.user.role.id) if request.user.role else None,
                'role_name': request.user.role.name if request.user.role else None,
            }
        })


# =====================================================
# 用户管理 ViewSet
# =====================================================

class UserManageViewSet(viewsets.ModelViewSet):
    """
    系统用户管理 ViewSet（CRUD）
    
    管理员可以：
    - 创建、查看、编辑、删除用户
    - 管理用户的角色
    
    权限说明：
    - 只有系统管理员可以访问此 ViewSet
    """
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
            # 普通用户只能查看自己
            return User.objects.filter(id=user.id)
        
        return User.objects.select_related('role').all()

    def perform_destroy(self, instance):
        # 不能删除自己
        if instance == self.request.user:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("不能删除自己的账号")
        instance.delete()

    def get_permissions(self):
        """
        SaaS RBAC 权限检查：
        - 写入操作 (create/update/partial_update/destroy) 需要 user.manage 权限
        - 读取操作 (list/retrieve) 需要 user.view 权限
        - 超管（super-admin / is_superuser）自动放行
        """
        from system.saas.permissions import UserManagePermission, UserViewPermission
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), UserManagePermission()]
        if self.action == 'list':
            return [permissions.IsAuthenticated(), UserViewPermission()]
        # retrieve — 已登录即可（用户查看自己的详情通过其他端点）
        return [permissions.IsAuthenticated()]


class UserManageViewSetV2(UserManageViewSet):
    """
    用户管理 v2 ViewSet：继承 v1 的 UserManageViewSet，仅通过 serializer_class
    切换到 v2 序列化器（增加 version 字段）。其余鉴权 / 过滤 / 分页 / 权限逻辑
    全部复用 v1，体现「版本迭代只重写差异」的推荐做法。
    """
    serializer_class = UserManageSerializerV2

