"""
API 签名验证中间件
"""

import json
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from loguru import logger

from .core import SignatureVerifier
from .exceptions import SignatureError


class APISignatureMiddleware(MiddlewareMixin):
    """
    API 签名验证中间件

    对指定的 API 路径进行签名验证

    配置：
    - API_SIGNATURE_ENABLED: 是否启用（默认 True）
    - API_SIGNATURE_PATHS: 需要验证的路径列表（支持通配符）
    - API_SIGNATURE_EXCLUDE_PATHS: 排除的路径列表
    """

    # 请求头名称
    HEADER_SIGNATURE = 'HTTP_X_API_SIGNATURE'
    HEADER_TIMESTAMP = 'HTTP_X_API_TIMESTAMP'
    HEADER_NONCE = 'HTTP_X_API_NONCE'
    HEADER_ACCESS_KEY = 'HTTP_X_API_ACCESS_KEY'

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.enabled = getattr(settings, 'API_SIGNATURE_ENABLED', True)
        self.include_paths = getattr(settings, 'API_SIGNATURE_PATHS', ['/api/*'])
        self.exclude_paths = getattr(settings, 'API_SIGNATURE_EXCLUDE_PATHS', [])
        self.verifier = SignatureVerifier()

    def process_request(self, request):
        if not self.enabled:
            return None

        # 检查路径是否需要验证
        if not self._should_verify_path(request.path):
            return None

        # 浏览器页面请求(HTML)或已登录会话用户跳过签名验证
        # 签名验证仅针对无会话的程序化 API 调用
        if self._is_browser_request(request):
            return None

        try:
            # 从请求头获取参数
            signature = request.META.get(self.HEADER_SIGNATURE, '')
            timestamp = int(request.META.get(self.HEADER_TIMESTAMP, 0))
            nonce = request.META.get(self.HEADER_NONCE, '')
            access_key = request.META.get(self.HEADER_ACCESS_KEY, '')

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

            # 验证签名
            self.verifier.verify_request(
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
            return None

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

    def _should_verify_path(self, path: str) -> bool:
        """
        检查路径是否需要验证

        Args:
            path: 请求路径

        Returns:
            bool: 是否需要验证
        """
        # 检查是否在排除列表
        for exclude_path in self.exclude_paths:
            if self._path_match(path, exclude_path):
                return False

        # 检查是否在包含列表
        for include_path in self.include_paths:
            if self._path_match(path, include_path):
                return True

        return False

    @staticmethod
    def _is_browser_request(request) -> bool:
        """
        判断是否为浏览器请求(跳过签名验证)。

        签名验证面向无会话的程序化 API 调用(服务端到服务端、移动端等)。
        浏览器页面请求和已登录会话用户走 Session/JWT 认证，不需要签名。

        判定条件(满足任一即跳过):
        1. Accept 头包含 text/html → 浏览器页面加载
        2. 已通过 Session 认证 → request.user.is_authenticated 且有 session
        """
        accept = request.META.get('HTTP_ACCEPT', '')
        if 'text/html' in accept:
            return True

        if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
            return True

        return False

    def _path_match(self, path: str, pattern: str) -> bool:
        """
        简单的路径匹配（支持 * 通配符）

        Args:
            path: 请求路径
            pattern: 匹配模式

        Returns:
            bool: 是否匹配
        """
        if '*' not in pattern:
            return path == pattern

        # 简单的通配符匹配
        pattern_parts = pattern.split('*')
        if len(pattern_parts) == 1:
            return path == pattern

        if not path.startswith(pattern_parts[0]):
            return False

        if not pattern_parts[-1] and path.endswith(pattern_parts[-2]):
            return True

        remaining = path[len(pattern_parts[0]):]
        for part in pattern_parts[1:-1]:
            if part not in remaining:
                return False
            idx = remaining.index(part)
            remaining = remaining[idx + len(part):]

        return remaining.endswith(pattern_parts[-1]) if pattern_parts[-1] else True
