"""
Request-ID 日志过滤器
将 Request-ID 注入到每条日志记录中，实现日志链路追踪
"""
import logging

from .middleware import get_request_id


class RequestIDFilter(logging.Filter):
    """
    日志过滤器：自动添加 request_id 字段
    """

    def filter(self, record):
        record.request_id = get_request_id() or "-"
        return True
