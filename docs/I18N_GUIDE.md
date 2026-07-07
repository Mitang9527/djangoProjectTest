# utils/i18n 使用指南

> Django i18n 的企业级增强包 —— 多租户 SaaS 场景下补齐 Django 自带 i18n 缺失的能力

## 目录

1. [背景与定位](#1-背景与定位)
2. [快速开始](#2-快速开始)
3. [API 全景](#3-api-全景)
4. [语言探测五级优先级](#4-语言探测五级优先级)
5. [数据库动态翻译](#5-数据库动态翻译)
6. [错误消息本地化](#6-错误消息本地化)
7. [DRF 集成](#7-drf-集成)
8. [租户级语言偏好](#8-租户级语言偏好)
9. [非请求上下文](#9-非请求上下文)
10. [管理命令](#10-管理命令)

---

## 1. 背景与定位

### Django 自带 i18n 解决了什么
- `.po` / `.mo` 翻译文件
- `LocaleMiddleware` 按 `Accept-Language` 探测
- `_("...")` / `gettext_lazy("...")` 翻译函数

### Django 自带 i18n 没解决什么（i18n 包补齐）

| 需求 | Django 自带 | i18n 包 |
|------|------------|---------|
| Header 探测 | ✅ | ✅（一致） |
| Query `?lang=` 探测 | ❌ | ✅ |
| Cookie 探测 | ✅ | ✅（一致） |
| User 偏好探测 | ❌ | ✅ |
| **租户级默认语言** | ❌ | ✅ |
| 探测顺序可配置 | ❌ | ✅ `I18N_DETECTORS` |
| 数据库动态翻译 | ❌ | ✅ `Translation` 模型 |
| 翻译完整度统计 | ❌ | ✅ `i18n_stats` 命令 |
| API 错误消息本地化 | ❌ | ✅ `localized_error_response()` |
| 翻译覆盖率 CI 校验 | ❌ | ✅ `--check` 模式 |
| Celery 任务上下文 | 需手动 | ✅ `force_language()` |
| 复数翻译 `%d` 自动格式化 | ❌ | ✅ |

---

## 2. 快速开始

### 2.1 安装

无需安装（已随项目 `utils/` 提供）。

### 2.2 启用中间件（替换默认 LocaleMiddleware）

```python
# settings.py
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "utils.i18n.middleware.I18nMiddleware",  # 替代 django.middleware.locale.LocaleMiddleware
    ...
]
```

### 2.3 DRF 视图

```python
from utils.i18n import t, LocalizedAPIView

class MyView(LocalizedAPIView):
    def get(self, request):
        # request.api_language 已经被探测+激活
        return Response({"message": t("common.welcome")})
```

### 2.4 普通 Django 视图

中间件已自动激活，`t()` / `_()` 即可使用。

### 2.5 翻译后端选择

```python
# settings.py
# 默认：CacheTranslationBackend（基于 Django cache，零 DB 依赖）
# I18N_TRANSLATION_BACKEND = "cache"  # 默认值

# 切换到 ORM 后端（需要先 migrate）
# I18N_TRANSLATION_BACKEND = "orm"
```

---

## 3. API 全景

### 3.1 语言代码处理

```python
from utils.i18n import normalize_language_code, is_supported_language, get_supported_languages

normalize_language_code("zh_CN")      # 'zh-hans'
normalize_language_code("ZH-cn")      # 'zh-hans'
normalize_language_code("en-GB")      # 'en'
normalize_language_code("fr-CA")      # 'fr-ca'
normalize_language_code("ja-JP")      # 'ja'

is_supported_language("zh-hans")      # True
is_supported_language("xyz")          # False

get_supported_languages()
# [('zh-hans', '简体中文'), ('en', 'English'), ('ja', '日本語')]
```

### 3.2 Accept-Language 解析与协商

```python
from utils.i18n import parse_accept_language, negotiate_language

# 解析
parse_accept_language("zh-CN,en-US;q=0.8,ja;q=0.5")
# [('zh-CN', 1.0), ('en-US', 0.8), ('ja', 0.5)]

# 协商
negotiate_language(["zh_CN", "en"], ["zh-hans", "en"])
# 'zh-hans'

negotiate_language(["ja-JP"], ["zh-hans", "en"])
# None（不支持）

negotiate_language(["ja-JP"], ["ja", "en"])
# 'ja'（主语言 fallback）
```

### 3.3 激活与切换

```python
from utils.i18n import activate_language, activate_for_request, get_current_language, force_language

# 手动激活
activate_language("zh_CN")      # 'zh-hans'

# 按请求激活（DRF 用）
activate_for_request(request)   # 自动探测 + 激活

# 查询
get_current_language()          # 'zh-hans'

# 上下文切换
with force_language("en"):
    send_email(...)             # 邮件模板用英文
# 退出后自动恢复
```

### 3.4 翻译函数

```python
from utils.i18n import t, tn, pget

# 单数翻译
t("common.save_success")                    # 按当前语言查
t("common.save_success", default="Saved")   # 兜底
t("common.save_success", lang="en")         # 显式指定语言

# 复数翻译
tn("1 item", "%d items", 1)        # '1 item'
tn("1 item", "%d items", 5)        # '5 items'

# 带上下文
pget("button", "Save")             # 翻译 "Save" in button context

# 懒翻译（用于 model verbose_name 等）
from utils.i18n import lazy_t, lazy_tn
class MyModel(models.Model):
    name = models.CharField(verbose_name=lazy_t("model.name"))
```

### 3.5 错误消息本地化

```python
from utils.i18n import localize_error, localized_error_response

# 函数式
msg = localize_error("user.email_exists")
# '邮箱已存在'

# 占位符
msg = localize_error("order.amount_invalid", amount=100)
# '金额 100 无效'

# DRF 响应
raise ValidationError(localize_error("user.email_exists"))

# 或直接返回响应
return localized_error_response(
    "order.amount_invalid",
    http_status=400,
    amount=100,
)
# Response({
#   'code': 'order.amount_invalid',
#   'message': '金额 100 无效',
#   'params': {'amount': 100}
# })
```

---

## 4. 语言探测五级优先级

### 默认优先级

```python
# utils/i18n/core.py
_DEFAULT_DETECTORS = ("header", "query", "cookie", "user", "tenant", "default")
```

| 级别 | 来源 | 示例 |
|------|------|------|
| 1 | `Accept-Language` header | `Accept-Language: zh-CN,en;q=0.8` |
| 2 | Query 参数 | `?lang=en` |
| 3 | Cookie | `Cookie: django_language=en` |
| 4 | 已登录用户偏好 | `request.user.language = "en"` |
| 5 | 租户默认语言 | `request.tenant.default_language = "en"` |
| 6 | 项目默认 | `settings.LANGUAGE_CODE = "zh-hans"` |

### 自定义探测顺序

```python
# settings.py
I18N_DETECTORS = ("query", "header", "cookie", "user", "tenant", "default")
# ↑ 让 query 优先于 header（适合内部 API）
```

### 自定义参数名

```python
# settings.py
I18N_PARAMS = {
    "query_name": "locale",          # ?locale=en
    "cookie_name": "myapp_lang",     # Cookie: myapp_lang=en
    "user_attr": "preferred_lang",   # request.user.preferred_lang
    "tenant_attr": "default_locale", # request.tenant.default_locale
}
```

---

## 5. 数据库动态翻译

### 场景

运营/租户后台需要热更新文案（如"限时优惠"标题、按钮文案），不想走 .po 重新部署。

### 用法

```python
from utils.i18n import register_translation, t

# 注册一条翻译（无需重启）
register_translation("zh-hans", "promo.summer_sale", "夏日特惠")
register_translation("en", "promo.summer_sale", "Summer Sale")

# 业务代码（自动按当前语言）
t("promo.summer_sale")  # '夏日特惠' 或 'Summer Sale'
```

### 翻译查找优先级

`t(key)` 的查找顺序：

1. **Django .po/.mo 翻译**（编译过的 .mo 文件，最快）
2. **数据库翻译后端**（CacheBackend / ORMBackend）
3. **default 参数**
4. **key 本身**

### CacheBackend vs ORMBackend

| 后端 | 存储 | 适用场景 | 持久化 |
|------|------|----------|--------|
| `CacheTranslationBackend` | Django cache | 少量翻译 + 热更新 | 依赖 cache backend |
| `ORMTranslationBackend` | 数据库 `utils_i18n_translation` 表 | 中大量翻译 + 后台管理 | 数据库 |

切换：
```python
# settings.py
I18N_TRANSLATION_BACKEND = "orm"  # 或 "cache"（默认）
```

### ORMBackend 启用步骤

```python
# 1) 加入 INSTALLED_APPS
INSTALLED_APPS += ["utils.i18n.apps.I18nConfig"]

# 2) 迁移
# python manage.py makemigrations utils_i18n
# python manage.py migrate utils_i18n

# 3) settings.py
I18N_TRANSLATION_BACKEND = "orm"
```

### 批量注册（启动加载）

```python
# apps/saas/apps.py
from django.apps import AppConfig

class SaasConfig(AppConfig):
    def ready(self):
        from utils.i18n import register_translation
        register_translation("zh-hans", "saas.welcome", "欢迎使用 SaaS 控制台")
        register_translation("en", "saas.welcome", "Welcome to SaaS Console")
```

---

## 6. 错误消息本地化

### 占位符语法（两种都支持）

```python
# str.format 风格（推荐）
register_translation("zh-hans", "order.amount_invalid", "金额 {amount} 无效")
localize_error("order.amount_invalid", amount=100)  # '金额 100 无效'

# % 风格
register_translation("zh-hans", "order.amount_invalid", "金额 %(amount)s 无效")
localize_error("order.amount_invalid", amount=100)  # '金额 100 无效'
```

### DRF Serializer 错误翻译

```python
from utils.i18n import translate_serializer_errors

class MyView(APIView):
    def post(self, request):
        serializer = MySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": translate_serializer_errors(serializer.errors)},
                status=400,
            )
```

### 自定义错误码

```python
# errors.py（项目级）
ERROR_CODES = {
    "USER_EMAIL_EXISTS": "user.email_exists",
    "USER_INVALID_CREDENTIALS": "user.invalid_credentials",
    "ORDER_AMOUNT_INVALID": "order.amount_invalid",
}

# 注册翻译
from utils.i18n import register_translation

register_translation("zh-hans", "user.email_exists", "邮箱已被注册")
register_translation("en", "user.email_exists", "Email already registered")
register_translation("zh-hans", "user.invalid_credentials", "邮箱或密码错误")
register_translation("en", "user.invalid_credentials", "Invalid email or password")
```

---

## 7. DRF 集成

### 7.1 LocalizedAPIView 基类

```python
from utils.i18n import LocalizedAPIView

class MyView(LocalizedAPIView):
    def get(self, request):
        # request.api_language 已激活
        return Response({"lang": request.api_language})
```

### 7.2 ViewSet 集成

```python
from utils.i18n import LocalizedAPIView
from rest_framework.viewsets import ModelViewSet

class MyViewSet(LocalizedAPIView, ModelViewSet):
    queryset = MyModel.objects.all()
    serializer_class = MySerializer
```

### 7.3 错误响应

```python
from utils.i18n import localized_error_response

class MyView(APIView):
    def post(self, request):
        if not_valid:
            return localized_error_response(
                "user.email_exists",
                http_status=400,
                email=request.data.get("email"),
            )
```

### 7.4 中间件 + DRF 关系

中间件 `I18nMiddleware` 也会在 request 阶段激活语言；`LocalizedAPIView.initial()` 重复激活是幂等的（无副作用）。

如果只想要 DRF 层激活、不想用中间件：

```python
# settings.py
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    # 删掉 LocaleMiddleware / I18nMiddleware
    ...
]
# 视图继承 LocalizedAPIView 即可
```

---

## 8. 租户级语言偏好

### 模型字段

```python
# apps/saas/models.py
class Tenant(models.Model):
    name = models.CharField(max_length=100)
    default_language = models.CharField(
        max_length=16,
        default="zh-hans",
        help_text="租户默认语言（zh-hans / en / ja 等）",
    )
```

### 自动应用

中间件 `I18nMiddleware` 会读取 `request.tenant.default_language` 作为降级优先级。

### 租户后台管理

```python
# admin.py
from utils.i18n.models import Translation
@admin.register(Translation)
class TranslationAdmin(admin.ModelAdmin):
    list_display = ("key", "lang", "value", "is_active", "updated_at")
    list_filter = ("lang", "is_active", "namespace")
    search_fields = ("key", "value")
```

---

## 9. 非请求上下文

### Celery 任务

```python
from celery import shared_task
from utils.i18n import force_language

@shared_task
def send_welcome_email(user_id, lang):
    with force_language(lang):
        # 邮件模板里的 _("...") 按 lang 翻译
        from utils.i18n import t
        subject = t("email.welcome.subject")
        body = t("email.welcome.body", name=get_user(user_id).name)
        send_email(subject, body, to=...)
```

### Management Command

```python
# management/commands/export.py
from django.core.management.base import BaseCommand
from utils.i18n import force_language, t

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--lang", default="zh-hans")

    def handle(self, *args, **options):
        with force_language(options["lang"]):
            self.stdout.write(t("export.start"))
            ...
```

### 异步上下文

```python
# utils/cache_warmup.py 等
from utils.i18n import force_language

def warmup_for_lang(lang):
    with force_language(lang):
        from utils.i18n import t
        # 预热 cache
        for key in ["common.welcome", "common.save_success"]:
            t(key)
```

---

## 10. 管理命令

### 10.1 翻译完整度统计

```bash
# 列出所有语言覆盖率
python manage.py i18n_stats

# lang      total translated missing     coverage
# zh-hans       12         12       0      100.0%
# en            12          8       4       66.7%
# ja            12          0      12        0.0%

# 指定语言
python manage.py i18n_stats --lang en

# JSON 输出
python manage.py i18n_stats --format json

# CI 模式（不达标 exit 1）
python manage.py i18n_stats --check --min 0.8
# All languages pass 80.0% coverage  (exit 0)
# 或
# Coverage below 80.0%: en=66.7%  (exit 1)
```

### 10.2 扫描代码中的 gettext 调用

```bash
# 找出代码中调用但 .po 中缺失的 key
python manage.py i18n_scan

# 找出 .po 中存在但代码里没引用的 key（可清理）
python manage.py i18n_scan --unused
```

### 10.3 配合 CI

```yaml
# .github/workflows/ci.yml
- name: i18n coverage check
  run: |
    python manage.py i18n_stats --check --min 0.8
```

---

## 11. 常见问题

### Q1：如何扩展支持语言列表？

```python
# settings.py
LANGUAGES = [
    ("zh-hans", "简体中文"),
    ("zh-hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
]
```

### Q2：单页面切换语言（前端 URL）？

前端跳转 `/some-page?lang=en`，中间件会自动激活；或者用 cookie：

```javascript
// 前端
document.cookie = `django_language=${lang};path=/;max-age=31536000`;
window.location.reload();
```

### Q3：与 Django .po 的关系？

- **Django .po**：代码里 `_(...)` 的字面量翻译（编译时固定）
- **utils.i18n 数据库翻译**：运营/租户可改的动态文案

`register_translation` 是数据库翻译，会覆盖 .po 中同 key 的翻译。生产建议：

```python
# settings.py
# 部署阶段：使用 .po
# 运营阶段：register_translation 覆盖
```

### Q4：性能开销？

| 操作 | 开销 |
|------|------|
| `t(key)` 命中 .mo | ~1μs（Django 内置 C 加速） |
| `t(key)` 命中 cache backend | ~50μs（Redis） |
| `t(key)` 命中 ORM backend | ~1ms（含 cache 命中） |
| `parse_accept_language` | ~5μs |
| `negotiate_language` | ~5μs |
| `detect_language` 全链路 | ~100μs（其中 ORM 是大头） |

建议在高频路径用 `t(key, lang="en")` 跳过探测。

### Q5：i18n 包能完全替代 .po 吗？

**不能**。`.po` 翻译是代码编译产物（CI 检查翻译完整性），`register_translation` 是运行期热更新。两者互补：

- 静态文案（按钮、菜单）→ .po
- 动态文案（活动标题、租户公告）→ `register_translation`
