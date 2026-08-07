# framework/pagination — 统一分页工具

> 标准库级别、与 DRF 兼容的**统一分页封装**。支持 4 种分页策略、2 种调用方式、X-Pagination-* 响应头。

---

## 1. 4 种分页器

| 类 | 适用场景 | URL 形参 |
|----|---------|---------|
| `PageNumberPagination` | 后台管理 / 总页数展示 | `?page=2&page_size=20` |
| `LimitOffsetPagination` | 第三方对接 / SQL 风格 | `?limit=20&offset=40` |
| `CursorPagination` | 无限滚动 / 百万级 / 实时流 | `?cursor=eyJ2IjoxNzE3fQ` |
| `SearchResultPagination` | 搜索结果（带 query/took_ms） | `?page=1&q=foo` |
| `AutoPagination` | 跟随全局 `DEFAULT_PAGINATION_CLASS` | 自动 |

---

## 2. 安装

零新增依赖，仅 `rest_framework`。

把 `framework/pagination/` 放到 `framework/` 下即可。

---

## 3. 快速开始

### 3.1 全局配置

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "framework.pagination.AutoPagination",
    "PAGE_SIZE": 20,
}
```

### 3.2 视图层覆盖

```python
from framework.pagination import CursorPagination, PageNumberPagination

class LogViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = CursorPagination
    cursor_order_by = "-timestamp"  # 必须

class OrderViewSet(viewsets.ModelViewSet):
    pagination_class = PageNumberPagination
    page_size = 50
    max_page_size = 500
```

### 3.3 函数式（普通 view、Celery 任务、脚本）

```python
from framework.pagination import paginate_response, get_paginator

# 函数式：直接返回 dict（用于 Celery 任务、导出脚本）
def export_users():
    result = get_paginator("default", User.objects.all(), page=1, page_size=1000)
    return result.to_dict()

# 视图层：传入 request 自动生成 next/previous URL
def my_view(request):
    data = paginate_response(User.objects.all(), request, page=1, page_size=20)
    return Response(data)
```

### 3.4 Cursor 分页视图

```python
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    pagination_class = CursorPagination

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @property
    def cursor_order_by(self):
        return "-created_at"  # 注意是 property
```

---

## 4. 响应 schema

### PageNumber / LimitOffset / Search 响应

```json
{
  "count": 1234,
  "next": "https://api/items?page=3&page_size=20",
  "previous": "https://api/items?page=1&page_size=20",
  "page": 2,
  "pages": 62,
  "page_size": 20,
  "results": [...]
}
```

### Cursor 响应

```json
{
  "count": -1,
  "next": "https://api/notifications?cursor=eyJ2IjoxNzE3fQ",
  "previous": "https://api/notifications?cursor=...",
  "page_size": 20,
  "ordering": "-created_at",
  "results": [...]
}
```

### 响应头

```
X-Pagination-Count: 1234
X-Pagination-Page: 2
X-Pagination-Page-Size: 20
X-Pagination-Pages: 62
```

前端无需解析 body 即可知道分页信息。

---

## 5. Search 模式特有字段

```python
class SearchView(generics.ListAPIView):
    pagination_class = SearchResultPagination

    def list(self, request, *args, **kwargs):
        import time
        start = time.monotonic()

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response = self.get_paginated_response(serializer.data)

        # SearchResultPagination 不自动加这些，由视图层补
        response.data["query"] = request.query_params.get("q", "")
        response.data["took_ms"] = int((time.monotonic() - start) * 1000)
        return response
```

响应：
```json
{
  "count": 87,
  "results": [...],
  "query": "django",
  "took_ms": 23
}
```

---

## 6. 自定义分页器

```python
from framework.pagination import PageNumberPagination

class MyPagination(PageNumberPagination):
    page_size = 50
    max_page_size = 500
    page_query_param = "p"          # 改成 ?p=1
    page_size_query_param = "ps"    # 改成 ?ps=50

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["custom_field"] = "value"
        return response
```

---

## 7. 常见问题

### Q1: 怎么与 DRF 默认分页器共存？

本工具的 `PageNumberPagination` 不继承 `rest_framework.pagination.PageNumberPagination`，
但**协议完全兼容**。直接替换 `pagination_class` 即可。

### Q2: Cursor 分页遇到 ties（排序字段值重复）怎么办？

本实现按 `cursor_order_by` 单一字段排序。生产中通常配合主键 tiebreaker：

```python
class LogPagination(CursorPagination):
    ordering = "-created_at"
    # 注意：model 端 Meta.ordering 应已含 id，否则需要重写 paginate_queryset
```

或重写 `paginate_queryset` 加入 `.order_by(ordering, "id")`。

### Q3: 想给所有分页响应统一加字段？

```python
class UniversalPagination(PageNumberPagination):
    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["api_version"] = "v2"
        return response
```

### Q4: 错误处理

- `page_size` 非整数 → `400 {page_size: "必须是整数"}`
- `page_size=0` → `400 {page_size: "必须 >= 1"}`
- `page_size` 超过 max → clamp 到 max
- `page` 超过最大页 → `400 {page: "超出范围，最大 N"}`
- `cursor` 非法 → `400 "无效的游标"`

---

## 8. 限制

- 默认 `page_size=20`，可通过 `?page_size=` 调整，最大 `200`
- Cursor 分页**不计算总数**（O(N) 代价太高），`count` 永远为 `-1`
- `AutoPagination` 需要在 settings 中显式配置 `DEFAULT_PAGINATION_CLASS` 才生效

---

## 9. 测试

```bash
python -m unittest framework.pagination.tests -v
# 22 个测试用例，覆盖：
# - PaginatedResponse: 3
# - 函数式分页: 4
# - paginate_response: 3
# - page_size 边界: 5
# - Cursor 编码解码: 5
# - DRF 兼容: 2
```
