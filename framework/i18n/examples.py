# sync-init: skip
"""
i18n 工具使用示例
==================

直接 ``python -m framework.i18n.examples`` 跑通（无需启动 Django）。
需要先设置 DJANGO_SETTINGS_MODULE 才能使用 Django i18n，本示例使用 mock。
"""
from __future__ import annotations

import os
import sys

# 允许独立运行
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# 独立运行：使用最小 Django settings
import os as _os
from django.conf import settings as _dj_settings

if not _dj_settings.configured:
    _dj_settings.configure(
        DEBUG=False,
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=[],
        USE_I18N=True,
        LANGUAGE_CODE="zh-hans",
        LANGUAGES=[("zh-hans", "简体中文"), ("en", "English"), ("ja", "日本語")],
        SECRET_KEY="example-secret-key",
    )
    import django
    django.setup()

import django
django.setup()


from framework.i18n import (
    normalize_language_code,
    parse_accept_language,
    negotiate_language,
    activate_language,
    force_language,
    get_current_language,
    t,
    tn,
    localize_error,
    register_translation,
    get_translation_stats,
    get_supported_languages,
)


def example_1_normalize():
    """示例 1：语言代码规范化"""
    print("=" * 60)
    print("[1] normalize_language_code")
    print("=" * 60)
    for raw in ["zh_CN", "zh-Hans", "ZH-cn", "en_US", "ja", "fr-CA", ""]:
        print(f"  {raw!r:>20} -> {normalize_language_code(raw)!r}")


def example_2_accept_language():
    """示例 2：解析 Accept-Language"""
    print("\n" + "=" * 60)
    print("[2] parse_accept_language")
    print("=" * 60)
    for header in [
        "zh-CN,en-US;q=0.8,ja;q=0.5",
        "en-GB,en;q=0.9,zh;q=0.8",
        "fr-FR,fr;q=0.9,*;q=0.5",
        "",
    ]:
        parsed = parse_accept_language(header)
        print(f"  {header!r}")
        print(f"     -> {parsed}")


def example_3_negotiate():
    """示例 3：协商最佳语言"""
    print("\n" + "=" * 60)
    print("[3] negotiate_language")
    print("=" * 60)
    supported = ["zh-hans", "en", "ja"]
    for accepted in [
        ["zh-CN"],
        ["en-US"],
        ["ja-JP"],
        ["fr-FR"],   # 客户端请求法语但系统不支持
        ["zh-TW", "en"],  # zh-TW 不支持但 zh 主语言也不在，回退 en
    ]:
        result = negotiate_language(accepted, supported)
        print(f"  accepted={accepted}  supported={supported}")
        print(f"     -> {result!r}")


def example_4_activate():
    """示例 4：激活与查询当前语言"""
    print("\n" + "=" * 60)
    print("[4] activate_language / get_current_language")
    print("=" * 60)
    for lang in ["zh_CN", "en", "fr", "ja", None]:
        activated = activate_language(lang)
        current = get_current_language()
        print(f"  activate({lang!r}) -> {activated!r}  current={current!r}")


def example_5_force_context():
    """示例 5：force_language 上下文"""
    print("\n" + "=" * 60)
    print("[5] force_language context")
    print("=" * 60)
    activate_language("zh-hans")
    print(f"  before: {get_current_language()}")
    with force_language("en"):
        print(f"  inside: {get_current_language()}")
    print(f"  after:  {get_current_language()}")


def example_6_t_function():
    """示例 6：t() 翻译函数"""
    print("\n" + "=" * 60)
    print("[6] t() translate")
    print("=" * 60)
    # 注册数据库翻译
    register_translation("zh-hans", "demo.greeting", "你好，{}！")
    register_translation("en", "demo.greeting", "Hello, {}!")
    register_translation("zh-hans", "demo.farewell", "再见")
    register_translation("en", "demo.farewell", "Goodbye")

    activate_language("zh-hans")
    print(f"  zh-hans: {t('demo.greeting', 'Hi').format('世界')}")
    print(f"  zh-hans: {t('demo.farewell', 'Bye')}")

    activate_language("en")
    print(f"  en:      {t('demo.greeting', 'Hi').format('World')}")
    print(f"  en:      {t('demo.farewell', 'Bye')}")

    # 兜底：key 不存在时回退 default
    print(f"  fallback: {t('not.exist', default='(default msg)')}")


def example_7_tn_plural():
    """示例 7：tn() 复数翻译"""
    print("\n" + "=" * 60)
    print("[7] tn() plural")
    print("=" * 60)
    activate_language("en")
    for n in [0, 1, 5]:
        print(f"  en, n={n}: {tn('%d item', '%d items', n)}")
    activate_language("zh-hans")
    for n in [0, 1, 5]:
        print(f"  zh, n={n}: {tn('%d 个项目', '%d 个项目', n)}")


def example_8_localize_error():
    """示例 8：localize_error 错误本地化"""
    print("\n" + "=" * 60)
    print("[8] localize_error")
    print("=" * 60)
    register_translation("zh-hans", "err.email_exists", "邮箱 {} 已被注册")
    register_translation("en", "err.email_exists", "Email {} is already registered")
    register_translation("zh-hans", "err.amount_invalid", "金额 {amount} 无效")
    register_translation("en", "err.amount_invalid", "Amount {amount} is invalid")

    activate_language("zh-hans")
    print(f"  zh: {localize_error('err.email_exists', email='a@b.com')}")
    print(f"  zh: {localize_error('err.amount_invalid', amount=100)}")
    activate_language("en")
    print(f"  en: {localize_error('err.email_exists', email='a@b.com')}")
    print(f"  en: {localize_error('err.amount_invalid', amount=100)}")


def example_9_stats():
    """示例 9：翻译统计"""
    print("\n" + "=" * 60)
    print("[9] get_translation_stats")
    print("=" * 60)
    # 再注册几条
    register_translation("zh-hans", "demo.item1", "项目1")
    register_translation("en", "demo.item1", "Item 1")
    register_translation("zh-hans", "demo.item2", "项目2")
    # 故意不注册 demo.item2 的 en

    print("  supported langs:", [code for code, _ in get_supported_languages()])
    for lang in ["zh-hans", "en"]:
        stats = get_translation_stats(lang)
        print(f"  {lang}: {stats}")


def main():
    example_1_normalize()
    example_2_accept_language()
    example_3_negotiate()
    example_4_activate()
    example_5_force_context()
    example_6_t_function()
    example_7_tn_plural()
    example_8_localize_error()
    example_9_stats()
    print("\n[OK] All 9 examples passed.")


if __name__ == "__main__":
    main()
