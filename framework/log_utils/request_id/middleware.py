"""
Request-ID 链路追踪中间件

功能:
- 从请求头 X-Request-ID 读取或自动生成唯一 Request-ID
- 注入到 request 对象，方便后续使用
- 注入到日志上下文 (loguru contextualize)
- 写入到响应头 X-Request-ID，便于前端/客户端关联
- 贯穿 Sentry 事件标签

使用:
  # settings.py
  MIDDLEWARE = [
      ...
      'framework.log_utils.request_id.RequestIDMiddleware',
      ...  # 其他中间件在之后执行，可通过 request.request_id 访问
  ]

  # 业务代码中获取 Request-ID:
  from framework.log_utils.request_id import get_request_id
  rid = get_request_id()

  # 日志自动携带 Request-ID (loguru contextualize 自动绑定):
  from loguru import logger
  logger.info("处理请求")  # 日志中自动出现 request_id
"""
import uuid
import threading

from django.http import HttpRequest, HttpResponse
from loguru import logger

# ================================================================
# 线程本地存储 (兼容旧代码 + 非 loguru 场景)
# ================================================================
_local = threading.local()


def get_request_id() -> str | None:
    """获取当前请求的 Request-ID"""
    return getattr(_local, "request_id", None)


def set_request_id(rid: str | None) -> None:
    """设置当前请求的 Request-ID"""
    _local.request_id = rid


def clear_request_id() -> None:
    """清除当前请求的 Request-ID"""
    if hasattr(_local, "request_id"):
        del _local.request_id


# ================================================================
# 中间件
# ================================================================

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    """
    Request-ID 链路追踪中间件

    1. 从请求头读取 X-Request-ID，没有则生成 UUID
    2. 存入 request.request_id
    3. 存入线程本地存储（供日志、Sentry 等使用）
    4. 使用 loguru.contextualize() 绑定 request_id 到日志上下文
       所有后续 logger.info/error 等调用自动携带 request_id
    5. 响应时写入 X-Request-ID 头
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # 1. 获取或生成 Request-ID
        request_id = request.META.get(
            f"HTTP_{REQUEST_ID_HEADER.replace('-', '_').upper()}",
            str(uuid.uuid4()),
        )

        # 2. 存入 request 对象
        request.request_id = request_id

        # 3. 存入线程本地存储
        set_request_id(request_id)

        # 4. 关联到 Sentry
        try:
            import sentry_sdk
            sentry_sdk.set_tag("request_id", request_id)
        except ImportError:
            pass

        # 5. loguru contextualize: 绑定 request_id 到日志上下文
        #    在此 with 块内的所有 logger.xxx() 调用自动携带 request_id
        #    InterceptHandler 转发的标准 logging 也自动携带
        with logger.contextualize(request_id=request_id):
            response = self.get_response(request)

        # 6. 响应头写入 Request-ID
        response[REQUEST_ID_HEADER] = request_id

        # 7. 清理线程本地存储
        clear_request_id()

        return response

    def process_exception(self, request, exception):
        """异常时也清理线程本地存储"""
        clear_request_id()
        return None
