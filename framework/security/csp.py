"""
CSP 响应头中间件。

注入 ``Content-Security-Policy``，默认策略禁止内联脚本 / 第三方资源 / 被 iframe 嵌套，
缓解 XSS 与点击劫持。策略可经 ``settings.CSP_POLICY`` 覆盖，``CSP_ENABLED=False`` 关闭。

接入（可选）：
    MIDDLEWARE += ['framework.security.csp.CSPMiddleware']
"""
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


class CSPMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if getattr(settings, "CSP_ENABLED", True) and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = getattr(settings, "CSP_POLICY", DEFAULT_CSP)
        return response
