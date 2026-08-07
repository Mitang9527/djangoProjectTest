"""drf-spectacular 自定义 AutoSchema。

消除纯 ``APIView`` / ``@api_view``（既未声明 ``serializer_class``、也未用
``@extend_schema(responses=...)`` / ``request=...`` 声明结构）在生成 OpenAPI 文档时产生的
``unable to guess serializer`` 日志噪声。

行为约定：
- 普通 ``APIView`` / ``@api_view`` 且未显式声明响应结构时，响应侧默认 free-form object，
  既消除告警，又让这些（多为返回自由 JSON 的运维类）端点在文档中拥有响应描述；
- 请求侧对 ``GET``/``HEAD``/``DELETE`` 返回 ``None``（不画蛇添足），其余返回 free-form object；
- ``GenericAPIView``（ViewSet 等）始终走 drf-spectacular 原生逻辑，不受任何影响。
"""
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView

_SAFE_METHODS = ('GET', 'HEAD', 'DELETE')


class PermissiveAutoSchema(AutoSchema):
    """对未声明结构的普通 APIView 给出 free-form 兜底，避免猜测序列化器告警。"""

    def _get_serializer(self):
        view = self.view
        # 普通 APIView / @api_view 若不具备任何 serializer 能力，静默返回 None，
        # 阻止基类抛出 "unable to guess serializer" 噪声；同时不影响已声明 serializer 的视图。
        if isinstance(view, APIView) and not isinstance(view, GenericAPIView):
            if not (
                callable(getattr(view, 'get_serializer', None))
                or callable(getattr(view, 'get_serializer_class', None))
                or hasattr(view, 'serializer_class')
            ):
                return None
        return super()._get_serializer()

    def get_response_serializers(self):
        result = super().get_response_serializers()
        if result is None and not isinstance(self.view, GenericAPIView):
            return OpenApiTypes.OBJECT
        return result

    def get_request_serializer(self):
        result = super().get_request_serializer()
        if result is None and not isinstance(self.view, GenericAPIView):
            if getattr(self, 'method', 'GET') in _SAFE_METHODS:
                return None
            return OpenApiTypes.OBJECT
        return result
