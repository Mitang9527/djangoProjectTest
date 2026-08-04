"""
统一分页器模块。

从 viewsets.py 中独立出来，避免与 rest_framework.viewsets 的循环导入。

用法:
    # settings.py
    REST_FRAMEWORK = {
        'DEFAULT_PAGINATION_CLASS': 'djangoProjectTest.pagination.StandardPagination',
    }

    # ViewSet 中直接使用
    from djangoProjectTest.pagination import StandardPagination
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """标准分页器 — 可用于 ViewSet 或独立使用"""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200
    page_query_param = "page"
