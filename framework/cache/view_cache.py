"""
视图级缓存工具
- cache_page 增强版（支持标签化失效）
- 常用缓存时间常量
- 租户感知键名
"""
import hashlib
import functools
from typing import List, Optional, Callable
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_cookie, vary_on_headers
from loguru import logger

from .cache_manager import (
    CACHE_VERSION,
    _build_key,
    invalidate_by_tag,
    CacheStats, invalidate_by_pattern,
)

# =====================================================
# 缓存时间常量（秒）
# =====================================================
T_30_SECONDS = 30
T_1_MINUTE = 60
T_5_MINUTES = 300
T_15_MINUTES = 900
T_30_MINUTES = 1800
T_1_HOUR = 3600
T_6_HOURS = 21600
T_1_DAY = 86400

# =====================================================
# 缓存标签常量
# =====================================================
TAG_TENANT = "tenant"
TAG_USER = "user"
TAG_DASHBOARD = "dashboard"
TAG_PERMISSIONS = "permissions"
TAG_EXPORT = "export"
TAG_GATEWAY = "gateway"
TAG_SYSTEM = "system"


# =====================================================
# 辅助函数
# =====================================================

def _tenant_key(request) -> str:
    """获取当前请求的租户 ID"""
    tenant = getattr(request, 'tenant', None)
    return str(tenant.id) if tenant else "global"


def view_cache_key(request, prefix: str) -> str:
    """生成视图缓存键: v3:{prefix}:{tenant}:{user}:{path}:{query_hash}"""
    tenant = _tenant_key(request)
    user_id = str(request.user.id) if request.user.is_authenticated else "anon"
    path = hashlib.md5(request.path.encode()).hexdigest()[:12]

    # 查询参数加入键（避免不同参数返回相同缓存）
    query = hashlib.md5(request.META.get('QUERY_STRING', '').encode()).hexdigest()[:8]

    return f"{CACHE_VERSION}:view:{prefix}:{tenant}:{user_id}:{path}:{query}"


# =====================================================
# 视图缓存装饰器
# =====================================================

def cache_view(prefix: str, timeout: int = T_5_MINUTES,
               tags: List[str] = None,
               key_func: Optional[Callable] = None):
    """
    视图级缓存装饰器（增强版 Django cache_page）

    相比原生 cache_page：
    - 支持标签化批量失效
    - 自动包含租户 ID 到键名
    - 统计命中率

    用法:
        @cache_view("dashboard", timeout=T_1_MINUTE, tags=["dashboard"])
        @api_view(['GET'])
        def system_dashboard_api(request):
            ...

    Args:
        prefix: 键前缀
        timeout: 过期时间（秒），默认 5 分钟
        tags: 标签列表
        key_func: 自定义键生成函数（参数为 request），返回字符串
    """
    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # 跳过非 GET 请求
            if request.method != 'GET':
                return view_func(request, *args, **kwargs)

            # 生成键
            if key_func:
                cache_key = key_func(request)
            else:
                cache_key = view_cache_key(request, prefix)

            # 读缓存
            cached_response = cache.get(cache_key)
            if cached_response is not None:
                CacheStats.record_hit()
                return cached_response

            CacheStats.record_miss()
            response = view_func(request, *args, **kwargs)

            # 写缓存（只缓存成功的 2xx 响应）
            if 200 <= response.status_code < 300:
                cache.set(cache_key, response, timeout=timeout)
                CacheStats.record_set()

                # 标签映射
                if tags:
                    from .cache_manager import _add_tag_mapping
                    _add_tag_mapping(tags, cache_key)

            return response
        return wrapper
    return decorator


def cache_method(prefix: str, timeout: int = T_5_MINUTES,
                 tags: List[str] = None):
    """
    类视图方法缓存装饰器

    用法:
        class DashboardView(View):
            @method_decorator(cache_view("dashboard", T_1_MINUTE, tags=["dashboard"]))
            def dispatch(self, *args, **kwargs):
                return super().dispatch(*args, **kwargs)
    """
    return method_decorator(cache_view(prefix, timeout, tags), name='dispatch')


# =====================================================
# 缓存失效快捷方法
# =====================================================

def bust_dashboard():
    """清除仪表盘缓存"""
    return invalidate_by_tag(TAG_DASHBOARD)


def bust_permissions(user_id: int = None):
    """清除权限缓存"""
    count = invalidate_by_tag(TAG_PERMISSIONS)
    if user_id:
        count += invalidate_by_pattern("view", f"*perms*{user_id}*")
    return count


def bust_tenant_cache(tenant_id: int = None):
    """清除租户相关缓存"""
    count = invalidate_by_tag(TAG_TENANT)
    if tenant_id:
        count += invalidate_by_pattern("view", f"*tenant*{tenant_id}*")
    return count


def bust_export_cache():
    """清除导出缓存"""
    return invalidate_by_tag(TAG_EXPORT)


def bust_gateway_cache():
    """清除网关缓存"""
    return invalidate_by_tag(TAG_GATEWAY)


# =====================================================
# DRF api_view 专用缓存装饰器
# =====================================================

def drf_cache_view(prefix: str, timeout: int = T_5_MINUTES,
                   tags: List[str] = None, vary_on_user: bool = True):
    """
    DRF @api_view 专用缓存装饰器

    直接缓存 rest_framework.response.Response 对象（pickle 安全），
    避免缓存 Django TemplateResponse。

    用法:
        @api_view(['GET'])
        @drf_cache_view("dashboard", timeout=30)
        def system_dashboard_api(request):
            ...

    Args:
        prefix: 键前缀
        timeout: 过期时间（秒）
        tags: 标签列表
        vary_on_user: 是否按用户区分（默认 True，即不同用户看到不同缓存）
    """
    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method != 'GET':
                return view_func(request, *args, **kwargs)

            # 跳过认证失败请求
            if not request.user.is_authenticated and vary_on_user:
                return view_func(request, *args, **kwargs)

            cache_key = view_cache_key(request, prefix)
            cached_response = cache.get(cache_key)
            if cached_response is not None:
                CacheStats.record_hit()
                cached_response['X-Cache'] = 'HIT'
                return cached_response

            CacheStats.record_miss()
            response = view_func(request, *args, **kwargs)

            if 200 <= response.status_code < 300:
                # DRF 的 finalize_response() 在 handler 返回后才执行,
                # 此处手动补全 renderer 信息, 否则 response.render() 会断言失败
                if not getattr(response, 'accepted_renderer', None):
                    response.accepted_renderer = request.accepted_renderer
                    response.accepted_media_type = request.accepted_media_type
                    response.renderer_context = {
                        'view': None,
                        'request': request,
                        'response': response,
                    }
                response.render()
                cache.set(cache_key, response, timeout=timeout)
                CacheStats.record_set()
                if tags:
                    from .cache_manager import _add_tag_mapping
                    _add_tag_mapping(tags, cache_key)

            response['X-Cache'] = 'MISS'
            return response
        return wrapper
    return decorator
