from django.apps import apps
from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    UserRegisterSerializer, UserDetailSerializer, UserLoginSerializer, TestApiSerializer,
    CustomTokenObtainPairSerializer, RefreshTokenSerializer, LogoutSerializer, UserManageSerializer
)
from .permissions import IsAdminOrSelf, DataPermissionMixin
from loguru import logger
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes

User = get_user_model()

class TestApiView(APIView):
    """
    规范化测试接口
    
    演示如何编写一个符合 Swagger 规范和项目自动发现机制的接口。
    包括请求参数说明、序列化器关联以及响应示例。
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
        # 这里处理业务逻辑
        return Response(serializer.data, status=status.HTTP_201_CREATED)

from django.shortcuts import render, redirect
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from django.views.generic import TemplateView
from django.contrib import messages

class UserProfileTemplateView(TemplateView):
    template_name = 'users/profile.html'
    permission_classes = [permissions.IsAuthenticated] # Note: TemplateView doesn't use this by default, but good for reference

class UserRegisterView(generics.CreateAPIView):
    """用户注册视图 (支持页面和 API)"""
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [permissions.AllowAny]
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'users/register.html'

    @extend_schema(exclude=True)
    def get(self, request):
        return Response({})

    def perform_create(self, serializer):
        user = serializer.save()
        logger.info(f"新用户注册: {user.username}")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"注册失败: 用户输入无效 - {serializer.errors}")
            if request.accepted_renderer.format == 'html':
                messages.error(request, _("注册失败，请检查输入信息"))
                return Response({'error': serializer.errors}, template_name=self.template_name)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        self.perform_create(serializer)
        
        # 获取请求 IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
        logger.success(f"新用户注册成功: 用户名=[{serializer.validated_data['username']}], IP=[{ip}]")
        
        if request.accepted_renderer.format == 'html':
            messages.success(
                request,
                _("注册成功！欢迎您，%(username)s。请登录。") % {'username': serializer.validated_data['username']}
            )
            return redirect('users:login')
        return Response(serializer.data, status=status.HTTP_201_CREATED)

from django.utils import timezone
from datetime import timedelta
from django.conf import settings

class UserLoginView(APIView):
    """用户登录视图 (支持页面和 API)"""
    permission_classes = [permissions.AllowAny]
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'users/login.html'
    serializer_class = UserLoginSerializer

    @extend_schema(exclude=True)
    def get(self, request):
        return Response({})

    @extend_schema(
        summary="用户登录",
        description="用户身份验证，成功后返回 Token。",
        request=UserLoginSerializer,
        responses={
            200: OpenApiResponse(description="登录成功，返回 Token"),
            301: OpenApiResponse(description="账号不存在"),
            501: OpenApiResponse(description="密码错误")
        }
    )
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"登录失败: 数据验证不通过 - {serializer.errors}")
            if request.accepted_renderer.format == 'html':
                return Response({'error': _('用户名或密码格式错误')}, template_name=self.template_name)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        # 1. 检查账号是否存在
        if not User.objects.filter(username=username).exists():
            logger.warning(f"登录失败: 账号不存在 - [{username}]")
            if request.accepted_renderer.format == 'html':
                return Response({'error_type': 'account_missing', 'error': _('账号不存在')}, status=301, template_name=self.template_name)
            return Response({'error': _('账号不存在')}, status=301)

        # 2. 验证账号密码
        user = authenticate(username=username, password=password)
        
        if user:
            if not user.is_active:
                logger.warning(f"登录失败: 账号已被禁用 - [{username}]")
                if request.accepted_renderer.format == 'html':
                    return Response({'error': _('该账号已被禁用')}, template_name=self.template_name)
                return Response({'error': _('该账号已被禁用')}, status=status.HTTP_403_FORBIDDEN)

            # 获取请求 IP
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
            
            logger.success(f"用户登录成功: 用户名=[{user.username}], 角色=[{getattr(user, 'role', 'user')}], IP=[{ip}]")
            
            if request.accepted_renderer.format == 'html':
                from django.contrib.auth import login
                login(request, user)
                return redirect('/')
            
            # 使用 JWT 认证生成 token
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': {
                    'id': user.pk,
                    'username': user.username,
                    'email': user.email,
                    'nickname': getattr(user, 'nickname', ''),
                    'role': getattr(user, 'role', 'user'),
                }
            })
        
        # 3. 账号存在但密码错误
        logger.warning(f"登录失败: 密码错误 - [{username}--{password}]")
        if request.accepted_renderer.format == 'html':
            return Response({'error_type': 'password_error', 'error': _('密码错误')}, status=501, template_name=self.template_name)
        return Response({'error': _('密码错误')}, status=501)

class UserLogoutView(APIView):
    """用户登出视图 - 支持 JWT 和 Session"""
    permission_classes = [permissions.AllowAny]  # 允许未认证访问，避免 401
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]

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
                
                # 1.1 删除旧的 API Token（清理所有可能的认证）
                try:
                    from rest_framework.authtoken.models import Token
                    if Token.objects.filter(user=request.user).exists():
                        Token.objects.filter(user=request.user).delete()
                        logger.info("旧的 API Token 已删除")
                except Exception as e:
                    logger.warning(f"删除 API Token 失败: {e}")
                
                # 1.2 清理用户模型中的 token 字段
                if hasattr(request.user, 'token') and request.user.token:
                    request.user.token = None
                    request.user.save(update_fields=['token'])
                    logger.info("用户模型中的 token 字段已清空")
                
                # 1.3 退出 Session 登录 (针对 HTML 页面)
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
                    # 即使黑名单失败也继续，不影响登出流程
            
            if username:
                logger.info(f"用户登出成功: {username}")
            else:
                logger.info("匿名用户登出请求")
            
            # 判断请求来源：如果是浏览器表单提交（通常包含 HTML 渲染器）
            if request.accepted_renderer.format == 'html' or 'text/html' in request.headers.get('Accept', ''):
                messages.success(request, _("您已成功退出登录"))
                return redirect('/')
                
            return Response({'message': _('登出成功')}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"用户登出异常: {e}")
            if request.accepted_renderer.format == 'html':
                return redirect('/')
            return Response({'error': _('登出失败')}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserInfoView(generics.RetrieveUpdateAPIView):
    """用户信息查看和修改"""
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSelf]
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'users/profile.html'

    def get_object(self):
        # 如果 URL 中传了 pk，则获取指定用户（受 IsAdminOrSelf 保护）
        pk = self.kwargs.get('pk')
        if pk:
            return super().get_object()
        # 否则默认返回当前登录用户
        return self.request.user

    def get(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        if request.accepted_renderer.format == 'html':
            return Response({'user': instance, 'serializer': serializer})
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        """支持 HTML 表单通过 POST 方法修改信息"""
        return self.update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if not serializer.is_valid():
            logger.warning(f"更新用户信息失败: {serializer.errors}")
            if request.accepted_renderer.format == 'html':
                messages.error(request, _("更新失败，请检查输入信息"))
                return Response({'user': instance, 'error': serializer.errors}, template_name=self.template_name)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self.perform_update(serializer)
        logger.success(f"用户信息更新成功: {instance.username}")

        if request.accepted_renderer.format == 'html':
            messages.success(request, _("个人资料更新成功！"))
            return redirect('users:profile')
        return Response(serializer.data)

from rest_framework import filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from rest_framework import viewsets

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

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
    - **分页**：默认每页 10 条，支持 `page` 和 `page_size` 参数。
    """
    queryset = User.objects.all()
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
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
            
            # 1. 如果是已认证用户，清理所有可能的认证
            if request.user and request.user.is_authenticated:
                username = request.user.username
                
                # 删除旧的 API Token
                try:
                    from rest_framework.authtoken.models import Token
                    if Token.objects.filter(user=request.user).exists():
                        Token.objects.filter(user=request.user).delete()
                        logger.info("旧的 API Token 已删除")
                except Exception as e:
                    logger.warning(f"删除 API Token 失败: {e}")
                
                # 清理用户模型中的 token 字段
                if hasattr(request.user, 'token') and request.user.token:
                    request.user.token = None
                    request.user.save(update_fields=['token'])
                    logger.info("用户模型中的 token 字段已清空")
                
                # 退出 Session 登录
                from django.contrib.auth import logout
                logout(request)
            
            # 2. 处理 JWT 登出 - 将 refresh token 加入黑名单
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response({'error': '缺少 refresh token'}, status=status.HTTP_400_BAD_REQUEST)
            
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
            return Response({'error': '登出失败'}, status=status.HTTP_400_BAD_REQUEST)

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
        
        # 如果没有系统角色，自动运行 init_permissions 初始化
        if not Role.objects.filter(tenant__isnull=True).exists():
            from django.core.management import call_command
            try:
                call_command('init_permissions')
                logger.info('已自动运行 init_permissions 初始化系统角色')
            except Exception as e:
                logger.error(f'运行 init_permissions 失败: {e}')
                # 终极兜底：创建一个空壳 super-admin 角色
                from apps.saas.models import Permission as PermModel
                admin_role = Role.objects.create(
                    tenant=None,
                    name='超级管理员',
                    slug='super-admin',
                    description='系统超级管理员，拥有所有权限（由系统自动创建）',
                    is_system=True,
                    is_active=True
                )
                # 赋予所有已存在的权限
                all_perms = PermModel.objects.filter(is_active=True)
                if all_perms.exists():
                    admin_role.permissions.set(all_perms)
        
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
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['role', 'is_active']
    search_fields = ['username', 'email', 'nickname', 'mobile']
    ordering_fields = ['id', 'date_joined', 'username']
    ordering = ['-date_joined']

    def get_queryset(self):
        user = self.request.user
        from apps.saas.permissions import _is_super_admin
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
        from apps.saas.permissions import UserManagePermission, UserViewPermission
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), UserManagePermission()]
        if self.action == 'list':
            return [permissions.IsAuthenticated(), UserViewPermission()]
        # retrieve — 已登录即可（用户查看自己的详情通过其他端点）
        return [permissions.IsAuthenticated()]

