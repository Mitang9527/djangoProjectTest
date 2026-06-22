from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from loguru import logger
import traceback

from django.conf import settings

def global_exception_handler(exc, context):
    """
    统一异常处理：
    1. 记录详细的异常日志（包括堆栈）
    2. 返回规范的 JSON 响应格式
    """
    # 获取 DRF 默认的异常处理响应
    response = exception_handler(exc, context)

    # 获取请求信息
    request_obj = context.get('view').request
    view_name = context.get('view').__class__.__name__
    method = request_obj.method
    path = request_obj.path

    if response is not None:
        # 已知的 DRF 异常（如 400, 401, 403, 404 等）
        logger.warning(f"API 警告 [{method}] {path} - {view_name}: {exc}")
        # 这里不需要手动包装格式，CustomRenderer 会自动处理
        # 如果是 400 验证错误，response.data 通常是一个包含字段错误信息的字典或列表
    else:
        # 未捕获的服务器内部错误 (500)
        logger.error(f"系统异常 [{method}] {path} - {view_name}: {exc}\n{traceback.format_exc()}")
        response = Response(
            {
                'detail': '服务器内部错误，请联系管理员',
                'exception': str(exc) if settings.DEBUG else None
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
