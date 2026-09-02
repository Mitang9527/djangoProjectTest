"""
i18n 工具包
===========

Django 自带 i18n 只解决「翻译文件 + LocaleMiddleware」，本包补齐企业 SaaS 缺失能力：

- 租户级语言偏好（Tenant.default_language）
- 多源探测（Header / Query / Cookie / User / Tenant / Default）
- 数据库动态翻译（运营/租户后台改文案）
- API 错误消息本地化
- 非请求上下文（Celery task / management command）的激活器
- 翻译完整度统计 / 扫描

零新增依赖（只用 Django / DRF / cache 既有组件）。

快速开始
--------

**1. 启用**::

    # settings.py
    INSTALLED_APPS += ["framework.i18n"]
    MIDDLEWARE.insert(0, "framework.i18n.middleware.I18nMiddleware")

**2. 探测并激活语言（DRF View）**::

    from framework.i18n import activate_for_request
    lang = activate_for_request(request)

**3. 动态翻译（数据库驱动）**::

    from framework.i18n import t, register_translation
    register_translation("zh-hans", "common.save_success", "保存成功")
    message = t("common.save_success")   # 自动按当前语言

**4. 错误消息本地化**::

    from framework.i18n import localize_error
    raise ValidationError(localize_error("user.email_exists"))

**5. 非请求上下文激活**::

    from framework.i18n import activate_language
    with activate_language("en"):
        send_email(...)   # 邮件模板用英文

**6. 翻译完整度统计**::

    python manage.py i18n_stats
    python manage.py i18n_stats --lang en --check  # CI 模式
"""
from .core import (
    # 语言探测
    detect_language,
    negotiate_language,
    parse_accept_language,
    # 激活
    activate_language,
    activate_for_request,
    get_current_language,
    force_language,
    # 翻译函数
    t,
    tn,
    pget,
    nget,
    lazy_t,
    lazy_tn,
    # 错误本地化
    localize_error,
    # 语言元数据
    get_supported_languages,
    is_supported_language,
    normalize_language_code,
    # 租户偏好
    get_tenant_default_language,
)
from .translations import (
    TranslationBackend,
    get_translation_backend,
    reset_translation_backend,
    register_translation,
    unregister_translation,
    get_translation_stats,
)
from .exceptions import (
    I18nError,
    UnsupportedLanguageError,
    TranslationNotFoundError,
)

__all__ = [
    # 语言探测
    "detect_language",
    "negotiate_language",
    "parse_accept_language",
    # 激活
    "activate_language",
    "activate_for_request",
    "get_current_language",
    "force_language",
    # 翻译函数
    "t",
    "tn",
    "pget",
    "nget",
    "lazy_t",
    "lazy_tn",
    # 错误本地化
    "localize_error",
    # 语言元数据
    "get_supported_languages",
    "is_supported_language",
    "normalize_language_code",
    # 租户偏好
    "get_tenant_default_language",
    # 数据库翻译
    "TranslationBackend",
    "get_translation_backend",
    "reset_translation_backend",
    "register_translation",
    "unregister_translation",
    "get_translation_stats",
    # 异常
    "I18nError",
    "UnsupportedLanguageError",
    "TranslationNotFoundError",
]
