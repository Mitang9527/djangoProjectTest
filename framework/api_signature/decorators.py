"""
API 签名验证装饰器
"""

import json
from functools import wraps
from django.http import JsonResponse
from django.conf import settings
from loguru import logger

from .core import SignatureVerifier
from .exceptions import SignatureError


def require_signature(
    secret_key: str = None,
    timestamp_tolerance: int = None,
    nonce_ttl: int = None,
):
    """
    API 签名验证装饰器

    Args:
        secret_key: 密钥（可选）
        timestamp_tolerance: 时间戳容忍度（可选）
        nonce_ttl: nonce 有效期（可选）

    Usage:
        @require_signature()
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 初始化验证器
            verifier = SignatureVerifier(
                secret_key=secret_key,
                timestamp_tolerance=timestamp_tolerance,
                nonce_ttl=nonce_ttl,
            )

            try:
                # 从请求头获取参数
                signature = request.META.get('HTTP_X_API_SIGNATURE', '')
                timestamp = int(request.META.get('HTTP_X_API_TIMESTAMP', 0))
                nonce = request.META.get('HTTP_X_API_NONCE', '')
                access_key = request.META.get('HTTP_X_API_ACCESS_KEY', '')

                # 获取请求参数
                method = request.method
                path = request.path
                params = dict(request.GET)

                # 获取请求体
                body = None
                if request.body:
                    try:
                        body = json.loads(request.body.decode('utf-8'))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

                verifier.verify_request(
                    method=method,
                    path=path,
                    params=params,
                    body=body,
                    signature=signature,
                    timestamp=timestamp,
                    nonce=nonce,
                    access_key=access_key,
                )

                logger.debug(f"API 签名验证通过: {method} {path}")
                return view_func(request, *args, **kwargs)

            except SignatureError as e:
                logger.warning(f"API 签名验证失败: {str(e)} - {request.method} {request.path}")
                return JsonResponse(
                    {
                        'code': 403,
                        'message': f'签名验证失败: {str(e)}',
                        'data': None
                    },
                    status=403
                )
            except Exception as e:
                logger.error(f"API 签名验证异常: {str(e)}")
                return JsonResponse(
                    {
                        'code': 500,
                        'message': '服务器内部错误',
                        'data': None
                    },
                    status=500
                )

        return _wrapped_view
    return decorator


def require_nonce(
    nonce_ttl: int = None,
):
    """
    仅验证 nonce 的装饰器（不验证签名，用于防重放攻击

    Args:
        nonce_ttl: nonce 有效期（可选）

    Usage:
        @require_nonce()
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            from .core import RedisNonceStore, MemoryNonceStore

            nonce = request.META.get('HTTP_X_API_NONCE', '')
            if not nonce:
                return JsonResponse(
                    {
                        'code': 403,
                        'message': '缺少 nonce 参数',
                        'data': None
                    },
                    status=403
                )

            # 初始化 nonce 存储
            try:
                store = RedisNonceStore()
            except Exception:
                store = MemoryNonceStore()

            ttl = nonce_ttl or getattr(settings, 'API_NONCE_TTL', 600)

            if not store.store(nonce, int(request.META.get('HTTP_X_API_TIMESTAMP', 0)), ttl):
                return JsonResponse(
                    {
                        'code': 403,
                        'message': 'nonce 已被使用',
                        'data': None
                    },
                    status=403
                )

            return view_func(request, *args, **kwargs)

        return _wrapped_view
    return decorator
