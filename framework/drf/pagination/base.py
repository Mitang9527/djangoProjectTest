# sync-init: skip
"""分页核心：PageNumber(?page)/LimitOffset(?limit,offset)/Cursor(O(1) 游标)/SearchResult/Auto。

注意：DRF BasePagination 子类定义时触发 api_settings.PAGE_SIZE 访问，本文件用函数式动态创建避免类级 settings 访问，未配置 Django 也可导入。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param, remove_query_param


@dataclass
class PaginatedResponse:
    """统一分页响应结构（dataclass，便于跨层传递）"""
    count: int
    results: List[Any]
    next: Optional[str] = None
    previous: Optional[str] = None
    page: Optional[int] = None
    pages: Optional[int] = None
    page_size: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "count": self.count,
            "results": self.results,
        }
        if self.next is not None:
            out["next"] = self.next
        if self.previous is not None:
            out["previous"] = self.previous
        if self.page is not None:
            out["page"] = self.page
        if self.pages is not None:
            out["pages"] = self.pages
        if self.page_size is not None:
            out["page_size"] = self.page_size
        if self.meta:
            out["meta"] = self.meta
        return out


class BasePagination:
    """所有自定义分页器的基类（不依赖 DRF settings 即可导入）。

    与 DRF 默认差异：① 统一 schema(count/page/pages/page_size/meta)；② 自动注入 X-Pagination-* 头；
    ③ page_size 可动态指定（clamp 到 [1, max_page_size]）。
    """
    page_size: Optional[int] = None
    max_page_size: Optional[int] = None
    page_size_query_param: Optional[str] = "page_size"
    cursor_query_param: str = "cursor"
    invalid_page_message: str = "无效的分页参数"

    def get_page_size(self, request) -> Optional[int]:
        """支持 ?page_size= 动态调整，未传则用默认值"""
        if self.page_size_query_param:
            try:
                raw = request.query_params.get(self.page_size_query_param)
            except Exception:
                raw = None
            if raw:
                try:
                    size = int(raw)
                except (TypeError, ValueError):
                    raise ValidationError(
                        {self.page_size_query_param: "必须是整数"}
                    )
                if size < 1:
                    raise ValidationError(
                        {self.page_size_query_param: "必须 >= 1"}
                    )
                if self.max_page_size and size > self.max_page_size:
                    size = self.max_page_size
                return size
        return self.page_size

    def get_paginated_response_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "总记录数"},
                "next": {"type": "string", "format": "uri", "nullable": True},
                "previous": {"type": "string", "format": "uri", "nullable": True},
                "results": schema,
            },
        }

    def paginate_queryset(self, queryset, request, view=None):
        raise NotImplementedError

    def get_paginated_response(self, data):
        raise NotImplementedError

    def get_next_link(self) -> Optional[str]:
        return None

    def get_previous_link(self) -> Optional[str]:
        return None

    def finalize_response(self, request, response, *args, **kwargs):
        if isinstance(response, Response) and isinstance(response.data, dict):
            data = response.data
            for header, key in (
                ("X-Pagination-Count", "count"),
                ("X-Pagination-Page", "page"),
                ("X-Pagination-Page-Size", "page_size"),
                ("X-Pagination-Pages", "pages"),
            ):
                if key in data and data[key] is not None:
                    response[header] = str(data[key])
        return response


class PageNumberPagination(BasePagination):
    """经典分页 ?page=1&page_size=20，适用需展示总页数的场景。"""
    page_size: int = 20
    max_page_size: int = 200
    page_query_param: str = "page"
    invalid_page_message: str = "无效的页码"

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        page_size = self.get_page_size(request) or self.page_size
        if not page_size:
            return None

        try:
            count = queryset.count() if hasattr(queryset, "count") else len(list(queryset))
        except TypeError:
            count = len(list(queryset))

        try:
            page_num = int(request.query_params.get(self.page_query_param, 1))
        except (TypeError, ValueError):
            raise ValidationError({self.page_query_param: "必须是整数"})
        if page_num < 1:
            page_num = 1

        pages = max(1, (count + page_size - 1) // page_size)
        if page_num > pages and count > 0:
            raise ValidationError({"page": f"超出范围，最大 {pages}"})

        start = (page_num - 1) * page_size
        end = start + page_size
        items = list(queryset[start:end])

        self._meta = {
            "count": count,
            "page": page_num,
            "pages": pages,
            "page_size": page_size,
        }
        self._items = items
        return items

    def get_paginated_response(self, data):
        m = self._meta
        return Response({
            "count": m["count"],
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "page": m["page"],
            "pages": m["pages"],
            "page_size": m["page_size"],
            "results": data,
        })

    def get_next_link(self) -> Optional[str]:
        m = self._meta
        if m["page"] >= m["pages"]:
            return None
        url = self.request.build_absolute_uri().split("?")[0]
        return f"{url}?{self.page_query_param}={m['page'] + 1}&{self.page_size_query_param}={m['page_size']}"

    def get_previous_link(self) -> Optional[str]:
        m = self._meta
        if m["page"] <= 1:
            return None
        url = self.request.build_absolute_uri().split("?")[0]
        return f"{url}?{self.page_query_param}={m['page'] - 1}&{self.page_size_query_param}={m['page_size']}"


class LimitOffsetPagination(BasePagination):
    """传统 ?limit=20&offset=40，适用 SQL 风格/与第三方对接。"""
    default_limit: int = 20
    max_limit: int = 200
    limit_query_param: str = "limit"
    offset_query_param: str = "offset"

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        try:
            limit = int(request.query_params.get(self.limit_query_param, self.default_limit))
        except (TypeError, ValueError):
            raise ValidationError({self.limit_query_param: "必须是整数"})
        try:
            offset = int(request.query_params.get(self.offset_query_param, 0))
        except (TypeError, ValueError):
            raise ValidationError({self.offset_query_param: "必须是整数"})

        if limit < 1:
            raise ValidationError({self.limit_query_param: "必须 >= 1"})
        if offset < 0:
            raise ValidationError({self.offset_query_param: "必须 >= 0"})
        if limit > self.max_limit:
            limit = self.max_limit

        try:
            count = queryset.count() if hasattr(queryset, "count") else len(list(queryset))
        except TypeError:
            count = len(list(queryset))

        items = list(queryset[offset: offset + limit])

        self._meta = {
            "count": count,
            "limit": limit,
            "offset": offset,
        }
        return items

    def get_paginated_response(self, data):
        m = self._meta
        return Response({
            "count": m["count"],
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "limit": m["limit"],
            "offset": m["offset"],
            "results": data,
        })

    def get_next_link(self) -> Optional[str]:
        m = self._meta
        if m["offset"] + m["limit"] >= m["count"]:
            return None
        url = self.request.build_absolute_uri().split("?")[0]
        return f"{url}?{self.limit_query_param}={m['limit']}&{self.offset_query_param}={m['offset'] + m['limit']}"

    def get_previous_link(self) -> Optional[str]:
        m = self._meta
        if m["offset"] <= 0:
            return None
        url = self.request.build_absolute_uri().split("?")[0]
        prev_offset = max(0, m["offset"] - m["limit"])
        return f"{url}?{self.limit_query_param}={m['limit']}&{self.offset_query_param}={prev_offset}"


class CursorPagination(BasePagination):
    """游标分页 ?cursor=base64({"o": field, "v": value})，O(1) 翻页适合百万级/无限滚动。

    视图须设置: pagination_class=CursorPagination；cursor_order_by="-created_at"(必须)；
    cursor_order_field="id"(可选, ties 时排序)。
    """
    page_size: int = 20
    max_page_size: int = 200
    ordering: str = "-id"
    cursor_encode_errors: str = "无效的游标"

    def _encode_cursor(self, ordering: str, value: Any) -> str:
        raw = json.dumps({"o": ordering, "v": value}, default=str, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

    def _decode_cursor(self, cursor: str) -> Tuple[str, Any]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            return data["o"], data["v"]
        except Exception as exc:
            raise ParseError(self.cursor_encode_errors) from exc

    def get_ordering(self, request, queryset, view) -> str:
        """支持视图层覆盖 cursor_order_by"""
        if view is not None:
            return getattr(view, "cursor_order_by", None) or self.ordering
        return self.ordering

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        ordering = self.get_ordering(request, queryset, view)
        queryset = queryset.order_by(ordering)

        page_size = self.get_page_size(request) or self.page_size
        if not page_size:
            return None

        cursor = request.query_params.get(self.cursor_query_param)
        if cursor:
            order_field, cursor_value = self._decode_cursor(cursor)
            if order_field != ordering:
                raise ParseError("游标的排序方向与请求不一致")
            # 构造 WHERE 条件
            if ordering.startswith("-"):                queryset = queryset.filter(**{f"{ordering[1:]}__lt": cursor_value})
            else:
                queryset = queryset.filter(**{f"{ordering}__gt": cursor_value})

        items = list(queryset[: page_size + 1])
        has_next = len(items) > page_size
        items = items[:page_size]

        self._meta = {
            "ordering": ordering,
            "page_size": page_size,
            "has_next": has_next,
        }
        if has_next and items:
            last = items[-1]
            cursor_field = ordering.lstrip("-")
            self._next_cursor = self._encode_cursor(ordering, getattr(last, cursor_field))
        else:
            self._next_cursor = None
        self._prev_cursor = cursor  # 反向回退
        self._items = items
        return items

    def get_paginated_response(self, data):
        return Response({
            "count": -1,  # cursor 分页不计算总数（O(N) 代价太高）
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "page_size": self._meta["page_size"],
            "ordering": self._meta["ordering"],
            "results": data,
        })

    def get_next_link(self) -> Optional[str]:
        if not getattr(self, "_next_cursor", None):
            return None
        url = self.request.build_absolute_uri().split("?")[0]
        return f"{url}?{self.cursor_query_param}={self._next_cursor}"

    def get_previous_link(self) -> Optional[str]:
        if not getattr(self, "_prev_cursor", None):
            return None
        url = self.request.build_absolute_uri().split("?")[0]
        return f"{url}?{self.cursor_query_param}={self._prev_cursor}"


class SearchResultPagination(PageNumberPagination):
    """搜索结果分页：常规字段外，视图层可在响应 data 追加 query / took_ms / highlights / facets。

    视图用法：ListAPIView 中 paginate 后取 serializer.data，再追加
    response.data["took_ms"] = int((time.monotonic()-start)*1000); response.data["query"] = request.query_params.get("q","")。
    """
    page_size: int = 20
    max_page_size: int = 100


class AutoPagination(BasePagination):
    """按 settings.REST_FRAMEWORK.DEFAULT_PAGINATION_CLASS 自动选择分页器，视图无需指定。"""
    def paginate_queryset(self, queryset, request, view=None):
        from django.conf import settings
        from rest_framework.settings import api_settings as drf_settings
        self.request = request
        paginator_class = drf_settings.DEFAULT_PAGINATION_CLASS
        if not paginator_class:
            # 未配置时 fallback 到 PageNumberPagination
            inner = PageNumberPagination()
        elif isinstance(paginator_class, type):
            inner = paginator_class()
        else:
            inner = paginator_class
        self._inner = inner
        if hasattr(inner, "request"):
            inner.request = request
        return inner.paginate_queryset(queryset, request, view=view)

    def get_paginated_response(self, data):
        if hasattr(self._inner, "get_paginated_response"):
            return self._inner.get_paginated_response(data)
        return Response({"results": data})


def get_paginator(
    name: str = "default",
    queryset: Optional[Sequence] = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResponse:
    """非 DRF 场景的分页工具（普通函数/Celery 任务/脚本）：返回 PaginatedResponse，可用 .to_dict()。"""
    if queryset is None:
        queryset = []
    total = len(queryset)
    start = (page - 1) * page_size
    end = start + page_size
    slice_ = list(queryset[start:end])
    pages = (total + page_size - 1) // page_size if page_size else 1
    return PaginatedResponse(
        count=total,
        results=slice_,
        page=page,
        pages=pages,
        page_size=page_size,
    )


def paginate_response(
    queryset: Sequence,
    request,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """简化版：传 queryset + request（取 base url），返回可直接 Response() 的 dict（含 next/previous URL）。"""
    result = get_paginator("default", queryset, page=page, page_size=page_size)
    data = result.to_dict()
    # 构造 next/previous URL（首末页显式置 None）
    try:
        base = request.build_absolute_uri().split("?")[0]
        if result.page and result.page < result.pages:
            data["next"] = f"{base}?page={result.page + 1}&page_size={result.page_size}"
        else:
            data["next"] = None
        if result.page and result.page > 1:
            data["previous"] = f"{base}?page={result.page - 1}&page_size={result.page_size}"
        else:
            data["previous"] = None
    except Exception:
        data.setdefault("next", None)
        data.setdefault("previous", None)
    return data
