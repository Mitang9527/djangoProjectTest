# sync-init: skip
"""
分页工具 - 使用示例
===================

可直接 ``python -m utils.pagination.examples`` 跑通（无需 Django 启动）。
"""
from __future__ import annotations

import time
from typing import List

# 配置最小 Django（避免 DRF 类级 settings 访问失败）
import django
from django.conf import settings as _dj_settings
if not _dj_settings.configured:
    _dj_settings.configure(
        DEBUG=False,
        DATABASES={},
        INSTALLED_APPS=[],
        REST_FRAMEWORK={
            "PAGE_SIZE": 20,
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
        },
    )
    django.setup()

from utils.pagination.base import (
    BasePagination,
    CursorPagination,
    LimitOffsetPagination,
    PageNumberPagination,
    SearchResultPagination,
    get_paginator,
    paginate_response,
)


def example_1_function_paginator():
    """例 1: 函数式分页（最简）"""
    print("\n=== Example 1: 函数式分页 ===")
    items = list(range(1, 101))  # 模拟 100 条
    result = get_paginator("default", items, page=2, page_size=10)
    print(f"count={result.count}, page={result.page}/{result.pages}, "
          f"page_size={result.page_size}, first_result={result.results[0]}, last={result.results[-1]}")
    assert result.count == 100
    assert result.page == 2
    assert len(result.results) == 10
    assert result.results[0] == 11
    assert result.results[-1] == 20
    print("OK")


def example_2_page_number_simulation():
    """例 2: Page Number 分页（mock request）"""
    print("\n=== Example 2: Page Number 分页 ===")

    class FakeQS(dict):
        def get(self, k, default=None):
            return super().get(k, default)

    class FakeRequest:
        query_params = FakeQS(page="2", page_size="15")
        META: dict = {}

    paginator = PageNumberPagination()
    paginator.request = FakeRequest()

    # 直接调 get_page_size 验证
    size = paginator.get_page_size(FakeRequest())
    print(f"page_size from query={size}")
    assert size == 15

    # 大于 max_page_size 会被 clamp
    FakeRequest.query_params = FakeQS(page="1", page_size="999")
    size = paginator.get_page_size(FakeRequest())
    print(f"clamped to max_page_size={size}")
    assert size == paginator.max_page_size
    print("OK")


def example_3_cursor_simulation():
    """例 3: Cursor 编码/解码"""
    print("\n=== Example 3: Cursor 编码/解码 ===")
    paginator = CursorPagination()
    cursor = paginator._encode_cursor("-created_at", 1717000000)
    print(f"encoded cursor: {cursor}")
    ordering, value = paginator._decode_cursor(cursor)
    assert ordering == "-created_at"
    assert value == 1717000000
    print(f"decoded: ordering={ordering}, value={value}")
    print("OK")


def example_4_limit_offset_response():
    """例 4: paginate_response 函数"""
    print("\n=== Example 4: paginate_response 函数 ===")

    class FakeRequest:
        def build_absolute_uri(self):
            return "https://api.example.com/items?page=1"

    data = paginate_response(
        queryset=list(range(1, 51)),
        request=FakeRequest(),
        page=2,
        page_size=10,
    )
    print(f"data keys: {sorted(data.keys())}")
    print(f"next={data.get('next')}")
    print(f"previous={data.get('previous')}")
    assert data["count"] == 50
    assert data["page"] == 2
    assert data["next"].endswith("page=3&page_size=10")
    assert data["previous"].endswith("page=1&page_size=10")
    print("OK")


def example_5_search_result_integration():
    """例 5: SearchResultPagination 与视图层集成示例（仅展示调用模式）"""
    print("\n=== Example 5: SearchResultPagination 模式 ===")
    # 实际项目中的视图层使用模式（这里只 mock 关键路径）
    start = time.monotonic()

    paginator = SearchResultPagination()

    class FakeRequest:
        query_params = {"page": "1", "page_size": "20"}

    size = paginator.get_page_size(FakeRequest())
    print(f"SearchResultPagination page_size={size}")
    assert size == 20

    took_ms = int((time.monotonic() - start) * 1000)
    print(f"took_ms={took_ms} (模拟查询耗时)")
    print("OK")


def main():
    print("=" * 60)
    print("分页工具示例 - 运行中")
    print("=" * 60)
    example_1_function_paginator()
    example_2_page_number_simulation()
    example_3_cursor_simulation()
    example_4_limit_offset_response()
    example_5_search_result_integration()
    print("\n" + "=" * 60)
    print("全部示例通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
