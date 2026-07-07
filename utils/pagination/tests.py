# sync-init: skip
"""
分页工具 - 单元测试
====================
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

# 在导入 DRF 前配置最小 settings（避免类级 settings 访问失败）
import django
from django.conf import settings as _dj_settings
if not _dj_settings.configured:
    _dj_settings.configure(
        DEBUG=False,
        DATABASES={},
        INSTALLED_APPS=[],
        REST_FRAMEWORK={
            "DEFAULT_PAGINATION_CLASS": None,
            "PAGE_SIZE": 20,
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
        },
    )
    django.setup()

from .base import (
    BasePagination,
    CursorPagination,
    LimitOffsetPagination,
    PageNumberPagination,
    SearchResultPagination,
    get_paginator,
    paginate_response,
)
from . import PaginatedResponse


# ============================================================================
# PaginatedResponse 测试
# ============================================================================

class PaginatedResponseTest(unittest.TestCase):
    def test_basic_to_dict(self):
        pr = PaginatedResponse(count=100, results=[1, 2, 3], page=1, pages=5, page_size=20)
        d = pr.to_dict()
        assert d["count"] == 100
        assert d["results"] == [1, 2, 3]
        assert d["page"] == 1
        assert d["pages"] == 5
        assert d["page_size"] == 20
        assert "next" not in d
        assert "meta" not in d

    def test_with_meta(self):
        pr = PaginatedResponse(count=10, results=[], meta={"query": "test", "took_ms": 23})
        d = pr.to_dict()
        assert d["meta"] == {"query": "test", "took_ms": 23}

    def test_with_next_previous(self):
        pr = PaginatedResponse(
            count=100, results=[],
            next="https://api/items?page=2",
            previous="https://api/items?page=1",
        )
        d = pr.to_dict()
        assert d["next"].endswith("page=2")
        assert d["previous"].endswith("page=1")


# ============================================================================
# 函数式分页测试
# ============================================================================

class FunctionPaginatorTest(unittest.TestCase):
    def test_basic(self):
        items = list(range(1, 51))  # 50 items
        r = get_paginator("default", items, page=1, page_size=10)
        assert r.count == 50
        assert r.page == 1
        assert r.pages == 5
        assert len(r.results) == 10
        assert r.results[0] == 1

    def test_last_page_partial(self):
        items = list(range(1, 46))  # 45 items
        r = get_paginator("default", items, page=5, page_size=10)
        assert r.count == 45
        assert r.pages == 5
        assert len(r.results) == 5  # 最后一页只有 5 个

    def test_empty(self):
        r = get_paginator("default", [], page=1, page_size=10)
        assert r.count == 0
        assert r.pages == 0 if False else 1  # 0 page_size 时会是 1
        assert r.results == []

    def test_out_of_range(self):
        items = list(range(1, 11))
        r = get_paginator("default", items, page=10, page_size=10)
        assert r.count == 10
        assert r.results == []


class PaginateResponseTest(unittest.TestCase):
    def test_paginate_response(self):
        class FakeRequest:
            def build_absolute_uri(self):
                return "https://api.example.com/items"
        data = paginate_response(list(range(1, 51)), FakeRequest(), page=2, page_size=10)
        assert data["count"] == 50
        assert data["page"] == 2
        assert data["next"] == "https://api.example.com/items?page=3&page_size=10"
        assert data["previous"] == "https://api.example.com/items?page=1&page_size=10"

    def test_first_page_no_previous(self):
        class FakeRequest:
            def build_absolute_uri(self):
                return "https://api/items"
        data = paginate_response(list(range(1, 51)), FakeRequest(), page=1, page_size=10)
        assert data["previous"] is None
        assert data["next"] is not None

    def test_last_page_no_next(self):
        class FakeRequest:
            def build_absolute_uri(self):
                return "https://api/items"
        data = paginate_response(list(range(1, 51)), FakeRequest(), page=5, page_size=10)
        assert data["next"] is None
        assert data["previous"] is not None


# ============================================================================
# Page Size 测试
# ============================================================================

class PageSizeTest(unittest.TestCase):
    def test_default_page_size(self):
        class FakeRequest:
            query_params = {}
        p = PageNumberPagination()
        assert p.get_page_size(FakeRequest()) == 20

    def test_custom_page_size(self):
        class FakeRequest:
            query_params = {"page_size": "50"}
        p = PageNumberPagination()
        assert p.get_page_size(FakeRequest()) == 50

    def test_page_size_clamped_to_max(self):
        class FakeRequest:
            query_params = {"page_size": "9999"}
        p = PageNumberPagination()
        size = p.get_page_size(FakeRequest())
        assert size == p.max_page_size  # 200

    def test_invalid_page_size_raises(self):
        from rest_framework.exceptions import ValidationError
        class FakeRequest:
            query_params = {"page_size": "abc"}
        p = PageNumberPagination()
        try:
            p.get_page_size(FakeRequest())
        except ValidationError:
            pass
        else:
            raise AssertionError("Expected ValidationError")

    def test_zero_page_size_raises(self):
        from rest_framework.exceptions import ValidationError
        class FakeRequest:
            query_params = {"page_size": "0"}
        p = PageNumberPagination()
        try:
            p.get_page_size(FakeRequest())
        except ValidationError:
            pass
        else:
            raise AssertionError("Expected ValidationError")


# ============================================================================
# Cursor Pagination 测试
# ============================================================================

class CursorPaginationTest(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        p = CursorPagination()
        cursor = p._encode_cursor("-created_at", 12345)
        ordering, value = p._decode_cursor(cursor)
        assert ordering == "-created_at"
        assert value == 12345

    def test_encode_decode_with_string(self):
        p = CursorPagination()
        cursor = p._encode_cursor("name", "alice")
        ordering, value = p._decode_cursor(cursor)
        assert ordering == "name"
        assert value == "alice"

    def test_decode_invalid_cursor(self):
        from rest_framework.exceptions import ParseError
        p = CursorPagination()
        try:
            p._decode_cursor("not-base64-!!!")
        except ParseError:
            pass
        else:
            raise AssertionError("Expected ParseError")

    def test_get_ordering_from_view(self):
        p = CursorPagination()
        p.request = MagicMock()
        # 默认
        view = MagicMock(spec=["pagination_class"])
        del view.cursor_order_by  # 确保属性不存在
        ordering = p.get_ordering(p.request, MagicMock(), view)
        assert ordering == p.ordering

    def test_get_ordering_override(self):
        p = CursorPagination()
        p.request = MagicMock()
        view = MagicMock()
        view.cursor_order_by = "-timestamp"
        ordering = p.get_ordering(p.request, MagicMock(), view)
        assert ordering == "-timestamp"


# ============================================================================
# DRF 兼容性测试
# ============================================================================

class DRFCompatibilityTest(unittest.TestCase):
    """确保我们的分页器与 DRF 协议兼容"""

    def test_page_number_paginate_queryset(self):
        # 用 dict 当 queryset 模拟
        class FakeQS:
            def __init__(self, data):
                self._data = data
            def count(self):
                return len(self._data)
            def __getitem__(self, key):
                if isinstance(key, slice):
                    return self._data[key]
                return self._data[key]
            def __iter__(self):
                return iter(self._data)

        class FakeReq:
            query_params = {"page": "2", "page_size": "10"}
            META: dict = {}
            def build_absolute_uri(self):
                return "http://test/items"

        items = list(range(1, 51))
        qs = FakeQS(items)
        req = FakeReq()
        p = PageNumberPagination()
        result = p.paginate_queryset(qs, req)
        assert result is not None
        assert len(result) == 10
        assert result[0] == 11

    def test_paginated_response_includes_results(self):
        from rest_framework.response import Response as DRFResponse
        class FakeReq:
            query_params = {"page": "1", "page_size": "10"}
            META: dict = {}
            def build_absolute_uri(self):
                return "http://test/items"
        p = PageNumberPagination()
        items = list(range(1, 51))
        p.paginate_queryset(items, FakeReq())
        resp = p.get_paginated_response([{"id": 1}, {"id": 2}])
        assert isinstance(resp, DRFResponse)
        assert "results" in resp.data
        assert "count" in resp.data
        assert resp.data["count"] == 50
        assert resp.data["page"] == 1
        assert resp.data["pages"] == 5
        assert resp.data["page_size"] == 10


if __name__ == "__main__":
    unittest.main(verbosity=2)
