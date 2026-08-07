import json
from django.http import HttpResponse, JsonResponse
from django.utils.deprecation import MiddlewareMixin
from .masking import mask_data


class ResponseMaskingMiddleware(MiddlewareMixin):
    """API响应自动脱敏中间件"""

    EXCLUDE_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
    ]

    def process_response(self, request, response):
        for path in self.EXCLUDE_PATHS:
            if path in request.path:
                return response

        if isinstance(response, JsonResponse):
            try:
                content = response.content.decode('utf-8')
                data = json.loads(content)
                masked_data = mask_data(data)
                return JsonResponse(masked_data, safe=False, status=response.status_code)
            except Exception:
                pass
        elif isinstance(response, HttpResponse):
            try:
                content_type = response.get('Content-Type', '')
                if 'application/json' in content_type:
                    content = response.content.decode('utf-8')
                    data = json.loads(content)
                    masked_data = mask_data(data)
                    return JsonResponse(masked_data, safe=False, status=response.status_code)
            except Exception:
                pass

        return response
