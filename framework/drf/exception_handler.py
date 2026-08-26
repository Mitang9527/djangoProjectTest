from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from loguru import logger
import traceback

from django.conf import settings


# 生产环境通用消息（不暴露任何技术细节、内部路径、类名或堆栈）
_PROD_500_MESSAGE = "服务器内部错误，请联系管理员"
_PROD_400_MESSAGE = "请求参数有误或处理失败"


def _is_production() -> bool:
    """生产环境判定：DEBUG 关闭即视为生产。"""
    return not getattr(settings, "DEBUG", False)


def global_exception_handler(exc, context):
    """
    统一异常处理：
    1. 记录详细异常日志（含堆栈，供排查，不返回给客户端）
    2. 生产环境对服务器内部错误/技术细节脱敏，仅返回通用消息
    3. 返回规范 JSON（最终由 CustomRenderer 统一包装为五字段）

    脱敏策略：
    - 500 未捕获异常：生产环境绝不返回异常原文、类名、堆栈或内部路径，
      完整信息仅写入日志；开发环境(DEBUG=True)保留详情便于调试。
    - 400 字段校验错误(ValidationError)：默认保留字段级 errors（前端表单
      提示需要，且内容为静态校验文案、不含系统内部信息）；如安全规范要求
      连此类信息也隐藏，将 settings.PROD_MASK_VALIDATION_ERRORS 设为 True。
    """
    response = exception_handler(exc, context)

    # 防御式取值：异常上下文可能缺少 view / request（如中间件层抛错、
    # 或未经过标准 DRF 视图），避免异常处理器自身再抛出 AttributeError。
    view = context.get('view')
    request_obj = getattr(view, 'request', None) if view else None
    view_name = getattr(view, '__class__', type(None)).__name__ if view else 'UnknownView'
    method = getattr(request_obj, 'method', 'UNKNOWN')
    path = getattr(request_obj, 'path', 'UNKNOWN')
    is_prod = _is_production()

    if response is not None:
        # 已知 DRF 异常（400/401/403/404/405...）
        logger.warning("API 警告 [{}] {} - {}: {}", method, path, view_name, exc)

        # 生产环境可选的字段校验错误脱敏（默认关闭，保留前端提示所需信息）
        if is_prod and getattr(settings, "PROD_MASK_VALIDATION_ERRORS", False):
            if isinstance(exc, DRFValidationError):
                response.data = {"detail": _PROD_400_MESSAGE}
                response.status_code = status.HTTP_400_BAD_REQUEST
    else:
        # 未捕获的服务器内部错误 (500)
        logger.error(
            "系统异常 [{}] {} - {}: {}\n{}",
            method, path, view_name, exc, traceback.format_exc()
        )
        if is_prod:
            # 生产环境：绝不泄露异常原文、类名、堆栈或内部路径
            response = Response(
                {"detail": _PROD_500_MESSAGE},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        else:
            # 开发环境：保留完整详情便于调试
            response = Response(
                {
                    "detail": f"服务器内部错误: {exc}",
                    "exception": str(exc),
                    "traceback": traceback.format_exc(),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    return response
