from django.shortcuts import render
from django.views.generic import TemplateView
from loguru import logger
from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework import permissions
from django.conf import settings
from django.urls import get_resolver, URLPattern, URLResolver
import json
import os
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets, mixins

from utils.OtherUtils.get_system_config import get_system_info
from utils.timeUtils.time_control import nowtime
from utils.cache.view_cache import drf_cache_view, T_5_MINUTES
from .models import AuditLog
from .serializers import AuditLogSerializer

import random
import datetime

class IndexView(TemplateView):
    template_name = 'core/index.html'

    def get(self, request, *args, **kwargs):
        logger.info("访问了首页")
        return super().get(request, *args, **kwargs)

class SystemStatusView(APIView):
    """
    系统状态视图 — 带缓存（5 秒短时缓存，避免 CPU 采样过于频繁）
    """
    permission_classes = [permissions.AllowAny]
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'core/partials/system_status.html'
    serializer_class = None

    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        stats = {
            'cpu_usage': get_system_info()['cpu']['percent'],
            'mem_usage': get_system_info()['memory']['percent'],
            'active_users': random.randint(1, 100),
            'last_update': nowtime()
        }
        if request.accepted_renderer.format == 'json':
            return Response(stats)
        return Response({'stats': stats})


class WebSocketDemoView(TemplateView):
    """WebSocket 演示页面"""
    template_name = 'core/websocket_demo.html'

    def get(self, request, *args, **kwargs):
        logger.info("访问了 WebSocket 演示页面")
        return super().get(request, *args, **kwargs)

class ApiConfigView(APIView):
    """
    项目全局 API 接口文档视图
    """
    permission_classes = [permissions.AllowAny]
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'core/api_docs.html'

    # 定义接口的详细元数据（用于增强自动发现的内容）
    ENDPOINT_METADATA = {
        'users:register': {
            "name": _("用户注册"),
            "description": _("新用户注册接口，支持页面和 JSON 提交。"),
            "params": [
                {"name": "username", "type": "string", "desc": _("用户名")},
                {"name": "password", "type": "string", "desc": _("密码")},
                {"name": "password_confirm", "type": "string", "desc": _("确认密码")},
                {"name": "email", "type": "string", "desc": _("邮箱")}
            ],
            "sample_response": {
                "id": 1,
                "username": "new_user",
                "email": "user@example.com",
                "nickname": "小明",
                "mobile": "13800138000"
            }
        },
        'users:login': {
            "name": _("用户登录"),
            "description": _("用户身份验证。支持 Session 登录和 Token 获取。"),
            "params": [
                {"name": "username", "type": "string", "desc": _("用户名")},
                {"name": "password", "type": "string", "desc": _("密码")}
            ],
            "sample_response": {
                "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
                "user_id": 1,
                "username": "admin"
            }
        },
        'users:user-list': {
            "name": _("用户列表"),
            "description": _("获取系统用户列表。支持搜索、过滤和排序。"),
            "params": [
                {"name": "search", "type": "string", "desc": _("模糊搜索 (用户名/昵称/手机号)")},
                {"name": "role", "type": "string", "desc": _("角色过滤 (admin/user)")},
                {"name": "ordering", "type": "string", "desc": _("排序 (id, -date_joined)")}
            ],
            "sample_response": {
                "count": 1,
                "results": [{"id": 1, "username": "admin", "role": "admin"}]
            }
        }
    }

    def get_all_urls(self, resolver, prefix='', namespace=None):
        """递归获取所有 API 路由并按应用归类"""
        apps_data = {}
        
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                # 递归处理
                new_namespace = pattern.namespace or namespace
                sub_apps = self.get_all_urls(pattern, prefix + str(pattern.pattern), new_namespace)
                # 合并子应用的接口
                for app_name, endpoints in sub_apps.items():
                    if app_name not in apps_data:
                        apps_data[app_name] = []
                    apps_data[app_name].extend(endpoints)
                    
            elif isinstance(pattern, URLPattern):
                name = pattern.name
                if not name: continue
                
                full_name = f"{namespace}:{name}" if namespace else name
                path = (prefix + str(pattern.pattern)).replace('^', '').replace('$', '')
                
                # 排除非 API 路由和自身
                if not path.startswith('api/') or name == 'api-config' or 'admin' in path:
                    continue
                
                # 确定所属应用名
                app_label = namespace if namespace else _("Other")
                if app_label not in apps_data:
                    apps_data[app_label] = []
                
                # 获取元数据
                meta = self.ENDPOINT_METADATA.get(full_name, {})
                view_class = getattr(pattern.callback, 'view_class', None)
                
                sample_response = meta.get("sample_response")
                if sample_response:
                    sample_response = json.dumps(sample_response, indent=4, ensure_ascii=False)

                apps_data[app_label].append({
                    "id": full_name.replace(':', '-'),
                    "name": meta.get("name", name),
                    "path": path,
                    "method": self.get_methods(pattern),
                    "description": meta.get("description", view_class.__doc__.strip() if view_class and view_class.__doc__ else _("暂无描述")),
                    "params": meta.get("params", []),
                    "sample_response": sample_response
                })
        
        return apps_data

    def get_methods(self, pattern):
        view_class = getattr(pattern.callback, 'view_class', None)
        if view_class:
            methods = []
            for m in ['get', 'post', 'put', 'patch', 'delete']:
                if hasattr(view_class, m):
                    methods.append(m.upper())
            if not methods and hasattr(view_class, 'http_method_names'):
                methods = [m.upper() for m in view_class.http_method_names if m not in ['options', 'head']]
            return "/".join(methods) if methods else "GET"
        return "GET"

    @extend_schema(exclude=True)
    def get(self, request):
        if not request.user.is_authenticated:
            if request.accepted_renderer.format == 'html':
                return Response({'needs_auth': True})
            return Response({'detail': 'Authentication credentials were not provided.'}, status=401)

        resolver = get_resolver()
        apps_data = self.get_all_urls(resolver)
        
        # 转换为列表格式以便前端循环
        categorized_endpoints = []
        for app_name, endpoints in apps_data.items():
            if not endpoints: continue
            
            # 应用内排序
            endpoints.sort(key=lambda x: (0 if 'register' in x['id'] or 'login' in x['id'] else 1, x['name']))
            
            categorized_endpoints.append({
                "app_name": app_name.upper(),
                "endpoints": endpoints
            })
            
        # 应用间排序：USERS 排在前面
        categorized_endpoints.sort(key=lambda x: 0 if x['app_name'] == 'USERS' else 1)

        config_data = {
            "project_name": getattr(settings, 'PROJECT_NAME', 'Django Project'),
            "version": "v2.0.0",
            "base_url": request.build_absolute_uri('/').rstrip('/'),
            "categories": categorized_endpoints,
            "auth_scheme": _("Token Authentication"),
            "header_example": _("Authorization: Token <your_token>")
        }
        
        if request.accepted_renderer.format == 'html':
            return Response(config_data)
        return Response(config_data)

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
            return render(request, 'core/permission_denied.html')
        return super().dispatch(request, *args, **kwargs)
