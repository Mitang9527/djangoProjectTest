"""
分页工具包
==========

为 DRF 列表接口提供**统一、可扩展**的分页能力：

- **PageNumberPagination**：经典分页（page + page_size）
- **LimitOffsetPagination**：传统 limit/offset
- **CursorPagination**：游标分页（适合无限滚动 / 大数据量）
- **SearchResultPagination**：搜索结果分页（total + 耗时 + keyword 高亮）

设计原则：配置驱动（参数全从 settings 取）、响应统一（``{count, next, previous, results, meta}``）、
可插拔（可覆盖 ``paginate_queryset``）、可观测（内置 ``X-Pagination-*`` 响应头）。

快速开始
--------

**全局配置（settings.py）**::

    REST_FRAMEWORK = {
        "DEFAULT_PAGINATION_CLASS": "framework.drf.pagination.AutoPagination",
        "PAGE_SIZE": 20,
        "PAGINATION_MAX_PAGE_SIZE": 200,
    }

**视图层覆盖**::

    from framework.drf.pagination import CursorPagination, SearchResultPagination

    class LogViewSet(viewsets.ReadOnlyModelViewSet):
        pagination_class = CursorPagination
        cursor_order_by = "-timestamp"  # 必须字段

    class SearchView(generics.ListAPIView):
        pagination_class = SearchResultPagination
        # 返回 data 后自动包成 {count, results, query, took_ms}

**自定义参数**::

    # 前端传 ?page=2&page_size=50；响应头 X-Pagination-{Count,Page,Page-Size,Pages}
"""
# 注：base.py 内部已避免类级 settings 访问，可直接导入
from .base import (
    BasePagination,
    PaginatedResponse,
    PageNumberPagination,
    LimitOffsetPagination,
    CursorPagination,
    SearchResultPagination,
    AutoPagination,
    get_paginator,
    paginate_response,
)

__all__ = [
    "BasePagination",
    "PaginatedResponse",
    "PageNumberPagination",
    "LimitOffsetPagination",
    "CursorPagination",
    "SearchResultPagination",
    "AutoPagination",
    "get_paginator",
    "paginate_response",
]
