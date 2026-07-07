# sync-init: skip
"""
i18n 中间件
============

替代或补充 django.middleware.locale.LocaleMiddleware：

- 同样的 Header / Cookie 探测
- 额外支持 Query 参数（?lang=en）— DRF API 友好
- 额外支持 User / Tenant 偏好
- 把最终语言挂到 request.LANGUAGE_CODE 与 request.api_language
"""
from __future__ import annotations

import logging

from .core import activate_for_request

logger = logging.getLogger(__name__)


class I18nMiddleware:
    """
    启用方法::

        # settings.py
        MIDDLEWARE = [
            "django.contrib.sessions.middleware.SessionMiddleware",
            "utils.i18n.middleware.I18nMiddleware",  # 替代 LocaleMiddleware
            ...
        ]

    与 Django LocaleMiddleware 的区别：
    - 支持 query 参数
    - 支持 user/tenant 偏好
    - 探测顺序可通过 I18N_DETECTORS 配置
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 探测并激活
        try:
            lang = activate_for_request(request)
        except Exception as e:
            logger.warning("I18nMiddleware failed: %s", e)
            lang = None
        response = self.get_response(request)
        # 暴露给响应（便于客户端调试）
        if lang:
            response["Content-Language"] = lang
        return response
