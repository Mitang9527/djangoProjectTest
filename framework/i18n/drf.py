# sync-init: skip
"""
i18n 的 DRF 集成
================

- LocalizedAPIView：在 dispatch 前主动激活
- TranslatedErrorResponse：错误响应消息也走 i18n
- LocalizedSerializerMixin：自动翻译字段的 error_messages
"""
from __future__ import annotations

import logging
from typing import Any

from rest_framework import status as drf_status
from rest_framework.response import Response
from rest_framework.views import APIView

from .core import activate_for_request, localize_error, t

logger = logging.getLogger(__name__)


class LocalizedAPIView(APIView):
    """
    DRF 基类：自动按请求探测并激活语言。

    优先级：query ?lang= > header > cookie > user > tenant > default

    用法::

        class MyView(LocalizedAPIView):
            def get(self, request):
                from framework.i18n import t
                return Response({"msg": t("common.welcome")})
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # 在权限/认证之后，dispatch 业务之前激活语言
        activate_for_request(request)


def localized_error_response(
    code: str,
    http_status: int = drf_status.HTTP_400_BAD_REQUEST,
    default: str | None = None,
    **params: Any,
) -> Response:
    """
    构造一个本地化错误响应。

    >>> localized_error_response("user.email_exists", http_status=400)
    Response(status=400, data={"code": "user.email_exists", "message": "邮箱已存在"})

    >>> localized_error_response("order.amount_invalid", amount=100)
    Response(status=400, data={"code": "...", "message": "金额 100 无效"})
    """
    message = localize_error(code, default=default, **params)
    return Response(
        {
            "code": code,
            "message": message,
            "params": params or None,
        },
        status=http_status,
    )


def translate_serializer_errors(errors: dict | list, lang: str | None = None) -> dict | list:
    """
    翻译 DRF serializer 错误。

    DRF 默认 error_messages 是英文硬编码，本函数尝试用 i18n key 翻译。

    用法（在 ViewSet 里）::

        def create(self, request):
            serializer = MySerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"errors": translate_serializer_errors(serializer.errors)},
                    status=400,
                )
    """
    if isinstance(errors, dict):
        return {k: translate_serializer_errors(v, lang) for k, v in errors.items()}
    if isinstance(errors, list):
        return [translate_serializer_errors(item, lang) for item in errors]
    if isinstance(errors, str):
        # 尝试把整个串当 i18n key 翻译
        translated = t(errors, default=errors, lang=lang)
        return translated
    return errors
