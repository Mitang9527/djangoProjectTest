# utils/versioning — API 版本管理（灰度 / 弃用 / 多版本共存）

> 在 DRF 自带版本（`Accept: application/json; version=1.0`）之上，提供**灰度发布、流量切分、过期提示、自动降级**能力。

---

## 1. 它解决什么问题

| 场景 | 痛点 | 本工具方案 |
|------|------|----------|
| 上线 v3 时如何让一部分用户先体验？ | 直接切换全量风险大 | 灰度：10% 流量先到 v3，90% 还在 v2 |
| v1 准备下线，但还要保留几个月 | 用户还在用，老接口要标 Sunset | `Deprecation` / `Sunset` 响应头 + successor 提示 |
| v2 没有某方法，v3 才有 | 维护者要在 dispatch 里手写 if/else | `@versioned_view(min_version="v3")` 装饰器 |
| 后台任务需要强制使用某版本 | 没请求上下文 | `set_active_version("v3")` 线程本地 |
| 测试要测多版本 | 一遍遍换 URL | 同一 URL 自动根据 `X-API-Version` header 路由 |

---

## 2. 核心概念

```
VersionSpec ── 注册到 ──→ VersionRegistry（全局单例）
                              │
                              ├── get_registry().resolve(request) → VersionSpec
                              │
                              └── 中间件 → 写入 request.api_version
```

### 状态机

```
canary  ──→ active  ──→ deprecated  ──→ sunset
   │           │              │
   │           │              └─→ 响应头：Deprecation / Sunset
   │           └─→ is_default=True
   └─→ canary_weight / canary_match 决定流量
```

---

## 3. 安装

```bash
# 零新增依赖
```

把 `utils/versioning/` 放到 `utils/` 下，然后在 `settings.MIDDLEWARE` 末尾添加：

```python
MIDDLEWARE = [
    ...,
    "utils.versioning.middleware.VersioningMiddleware",
]
```

---

## 4. 快速开始

### 4.1 注册版本

```python
# apps/saas/apps.py
from django.apps import AppConfig

class SaasConfig(AppConfig):
    name = "apps.saas"
    def ready(self):
        from utils.versioning import register_version, VersionSpec, VersionStatus
        from datetime import date

        register_version(VersionSpec(
            name="v1",
            status=VersionStatus.DEPRECATED,
            deprecated_at=date(2026, 1, 1),
            sunset_date=date(2026, 12, 31),
            successor="v2",
        ))
        register_version(VersionSpec(
            name="v2",
            status=VersionStatus.ACTIVE,
            is_default=True,
            description="当前主版本",
        ))
        register_version(VersionSpec(
            name="v3",
            status=VersionStatus.CANARY,
            canary_weight=10,  # 10% 流量
            description="v3 灰度中",
        ))
```

### 4.2 视图层使用装饰器

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from utils.versioning import versioned_view, only_for, since, until


class OrderAPIView(APIView):

    @since("v2")  # 自 v2 起才有
    def post(self, request):
        return Response({"version": request.api_version})

    @until("v3")  # v3 之前可用，v3+ 返回 404
    def legacy_get(self, request):
        return Response({...})

    @only_for("v3")  # 仅 v3 可见（其他版本 404）
    def experimental(self, request):
        return Response({...})

    @versioned_view(min_version="v2", removed_in="v4")
    def list(self, request):
        # v1: 404
        # v2/v3: 200
        # v4+: 410 Gone
        return Response({...})
```

### 4.3 ViewSet 集成

```python
from utils.versioning import VersionedMixin, get_versioned_api_view

APIView = get_versioned_api_view()
MyBase = VersionedMixin  # 或同时使用 get_versioned_viewset()
```

### 4.4 探测顺序

默认按 **url → header → query** 顺序探测：

```bash
# URL 形式
GET /api/v2/orders

# Header 形式
GET /api/orders
X-API-Version: v2

# Query 形式
GET /api/orders?version=v2
```

可在 `settings.API_VERSIONING.detection_order` 中调整。

### 4.5 灰度规则

| 优先级 | 规则 | 用途 |
|--------|------|------|
| 1 | `canary_match` 自定义函数 | 任意业务规则 |
| 2 | `X-User-Tier: beta` Header | 内部测试人员 |
| 3 | `canary_weight` 百分比 | 按用户哈希均匀分布 |

```python
# 高级：仅 VIP 用户走 canary
v3 = VersionSpec(
    name="v3",
    status=VersionStatus.CANARY,
    canary_match=lambda req: getattr(req.user, "tier", "") == "vip",
)
```

---

## 5. 响应头

中间件自动注入：

```
X-API-Version-Requested: v3
X-API-Version-Served: v3
Deprecation: 2026-01-01          # 仅 deprecated 状态
Sunset: 2026-12-31                # 仅 deprecated 状态
Link: </api/v2/>; rel="successor-version"
```

---

## 6. 高级用法

### 6.1 后台任务强制指定版本

```python
from utils.versioning import set_active_version, get_active_version

def my_celery_task():
    set_active_version("v3")
    try:
        # 调用的内部 API 全部走 v3
        call_some_api()
    finally:
        set_active_version(None)
```

### 6.2 多版本 URL 路由

```python
# urls.py
from django.urls import path, re_path
from apps.saas.views import OrderAPIView

urlpatterns = [
    re_path(r"^api/v1/orders/$", OrderAPIView.as_view()),
    re_path(r"^api/v2/orders/$", OrderAPIView.as_view()),
    re_path(r"^api/v3/orders/$", OrderAPIView.as_view()),
    # URL 形式：客户端按版本访问
]
```

或统一前缀 + 中间件识别：

```python
# urls.py
urlpatterns = [
    path("api/orders/", OrderAPIView.as_view()),  # 单入口
]
# 客户端通过 ?version=v3 切换，中间件识别后写入 request.api_version
```

### 6.3 装饰器组合

```python
@versioned_view(min_version="v2", removed_in="v4")
@idempotent(key_fields=["order_id"], ttl=600)  # 可与 P0 utils 组合
@retry(max_attempts=3)
def create_order(order_id):
    ...
```

---

## 7. 与现有权限 / 租户系统集成

`request.api_version` 由中间件注入，可在权限类、限流器中读取：

```python
# utils/permissions.py
from rest_framework.permissions import BasePermission

class VersionedPermission(BasePermission):
    def has_permission(self, request, view):
        v = getattr(request, "api_version", None)
        if v == "v1" and not request.user.has_perm("api.v1_access"):
            return False
        return True
```

---

## 8. 常见问题

### Q1: 装饰器和 `versioned_view` 怎么选？

| 场景 | 推荐 |
|------|------|
| ViewSet 方法 | `@versioned_view(min_version="v2")` |
| 函数视图 | `@since("v2")` / `@until("v3")` / `@only_for("v3")` |
| 整个 ViewSet 都要新版本 | 继承 `VersionedMixin`，配合 URL 路由 |

### Q2: canary 灰度用户看到一半 v2 一半 v3 怎么办？

灰度规则基于 `request.user.pk` 哈希，**同一用户在同一 canary 配置下总是命中同一版本**。
如果修改了 `canary_weight`，才可能改变。

### Q3: sunset 状态的版本被请求时会怎样？

中间件返回 `410 Gone`：

```json
{
  "detail": "API 版本 v1 已停用",
  "successor": "v2"
}
```

### Q4: 同一 URL 既要 v2 又要 v3 怎么办？

用 Header：`X-API-Version: v3` + 单一 URL，中间件分发到不同逻辑。
或用装饰器 `@versioned_view` 在方法层做版本判断。

### Q5: 怎么测多版本？

```python
# tests.py
def test_v2_requires_v2_header(self):
    response = self.client.get("/api/orders", HTTP_X_API_VERSION="v2")
    self.assertEqual(response["X-API-Version-Served"], "v2")

def test_v1_deprecated_header(self):
    response = self.client.get("/api/orders", HTTP_X_API_VERSION="v1")
    self.assertIn("Sunset", response)
```

---

## 9. 限制

- `v3-beta` 与 `v3` 视为同一版本（简化版本号比较）
- 灰度权重基于 `hash(user.pk) % 100`，**仅适用于用户登录态**；匿名用户用 `IP+UA` 哈希
- 不存储版本级 schema 变更历史（如果需要建议配合 drf-spectacular）

---

## 10. 测试

```bash
python -m unittest utils.versioning.tests -v
# 38 个测试用例：
# - VersionSpec: 4
# - VersionRegistry: 6
# - 灰度规则: 6
# - 版本号比较: 4
# - 装饰器: 8
# - 探测: 6
# - 顶层 API: 4
```
