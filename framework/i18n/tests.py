# sync-init: skip
"""
i18n 工具单元测试
==================

28+ 个测试，覆盖：
- 语言代码规范化
- Accept-Language 解析
- 语言协商
- 多源探测（mock request）
- 激活与上下文
- 翻译函数（t / tn / pget）
- 错误本地化
- 数据库翻译后端
- 统计
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

# 独立运行：使用最小 Django settings（避免依赖 cachalot 等第三方包）
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
        SECRET_KEY="test-secret-key-not-for-production",
    )
    import django
    django.setup()


from django.test import override_settings

from framework.i18n import (
    normalize_language_code,
    parse_accept_language,
    negotiate_language,
    activate_language,
    force_language,
    get_current_language,
    is_supported_language,
    get_supported_languages,
    t,
    tn,
    pget,
    localize_error,
    register_translation,
    unregister_translation,
    get_translation_stats,
    reset_translation_backend,
)
from framework.i18n.translations import (
    CacheTranslationBackend,
    TranslationBackend,
)
from framework.i18n.exceptions import I18nError


# ============================================================
# 1. 语言代码规范化
# ============================================================


class NormalizeLanguageCodeTest(unittest.TestCase):

    def test_chinese_variants(self):
        self.assertEqual(normalize_language_code("zh_CN"), "zh-hans")
        self.assertEqual(normalize_language_code("zh-CN"), "zh-hans")
        self.assertEqual(normalize_language_code("zh"), "zh-hans")
        self.assertEqual(normalize_language_code("ZH_CN"), "zh-hans")
        self.assertEqual(normalize_language_code("zh-hant"), "zh-hant")
        self.assertEqual(normalize_language_code("zh_TW"), "zh-hant")

    def test_english_variants(self):
        self.assertEqual(normalize_language_code("en"), "en")
        self.assertEqual(normalize_language_code("EN"), "en")
        self.assertEqual(normalize_language_code("en_US"), "en")
        self.assertEqual(normalize_language_code("en-GB"), "en")

    def test_other_languages_passthrough(self):
        self.assertEqual(normalize_language_code("ja"), "ja")
        self.assertEqual(normalize_language_code("fr-CA"), "fr-ca")
        # ko-kr 收敛为 ko（主语言）
        self.assertEqual(normalize_language_code("ko_KR"), "ko")

    def test_empty(self):
        self.assertIsNone(normalize_language_code(""))
        self.assertIsNone(normalize_language_code(None))

    def test_whitespace(self):
        self.assertEqual(normalize_language_code("  zh_CN  "), "zh-hans")


# ⚠️ 必须显式 override：本文件支持两种运行方式（独立 `python tests.py` 走上面自建的
# 最小 settings；pytest 走 DJANGO_SETTINGS_MODULE），两者的 LANGUAGES 并不一致
# （settings.base 只开了 zh-hans + en，没有 ja）。不 override 的话 pytest 下
# is_supported_language("ja") 会返回 False 而失败。
_TEST_LANGUAGES = [("zh-hans", "简体中文"), ("en", "English"), ("ja", "日本語")]


class IsSupportedLanguageTest(unittest.TestCase):

    @override_settings(LANGUAGES=_TEST_LANGUAGES)
    def test_supported(self):
        self.assertTrue(is_supported_language("zh_CN"))
        self.assertTrue(is_supported_language("en"))
        self.assertTrue(is_supported_language("ja"))

    @override_settings(LANGUAGES=_TEST_LANGUAGES)
    def test_unsupported(self):
        self.assertFalse(is_supported_language("xyz"))

    @override_settings(LANGUAGES=_TEST_LANGUAGES)
    def test_empty(self):
        self.assertFalse(is_supported_language(""))
        self.assertFalse(is_supported_language(None))


# ============================================================
# 2. Accept-Language 解析
# ============================================================


class ParseAcceptLanguageTest(unittest.TestCase):

    def test_basic(self):
        result = parse_accept_language("zh-CN,en-US;q=0.8,ja;q=0.5")
        self.assertEqual(len(result), 3)
        # 按 q 降序：zh-CN(1.0), en-US(0.8), ja(0.5) — 保留原始大小写
        self.assertEqual(result[0], ("zh-CN", 1.0))
        self.assertEqual(result[1], ("en-US", 0.8))
        self.assertEqual(result[2], ("ja", 0.5))

    def test_no_q_value(self):
        result = parse_accept_language("zh-CN,en")
        self.assertEqual(result, [("zh-CN", 1.0), ("en", 1.0)])

    def test_empty(self):
        self.assertEqual(parse_accept_language(""), [])
        self.assertEqual(parse_accept_language(None), [])

    def test_q_sorting(self):
        result = parse_accept_language("a;q=0.1,b;q=0.9,c;q=0.5")
        # 保留原始大小写
        self.assertEqual([lang for lang, _ in result], ["b", "c", "a"])


# ============================================================
# 3. 语言协商
# ============================================================


class NegotiateLanguageTest(unittest.TestCase):

    def test_exact_match(self):
        self.assertEqual(
            negotiate_language(["zh_CN", "en"], ["zh-hans", "en"]),
            "zh-hans",
        )

    def test_no_match_fallback_to_primary(self):
        # 客户端要 zh-TW，但只支持 zh-hans：返回 zh-hans（如果该 primary 在支持集）
        # 但 zh-hans 不在主语言集，所以会回退
        result = negotiate_language(["zh_TW"], ["zh-hans", "en"])
        # zh-hans 算 zh 主语言吗？我们的实现是 "zh" 才是 primary
        # 协商应尝试 zh 匹配 supported，但 supported 没有 "zh"，所以 None
        # 但实际上我们用 normalize_language_code 后，zh_TW -> zh-hant
        # 而 supported 是 zh-hans，二者不等，且 primary = "zh" 也不在 supported
        # 所以最终是 None
        self.assertIsNone(result)

    def test_primary_fallback_works(self):
        # 客户端要 zh-TW，suported 是 zh-hans（primary zh 不在，但 zh-hans 在）
        # 因为 zh-hans ≠ zh-hant，且 primary=zh 不在 supported，返 None
        # 但实际项目里 supported 通常是 ['zh-hans', 'en']，primary zh 不在
        # 用另一个变体：客户端 ja-JP，suported ['ja', 'en']
        result = negotiate_language(["ja-JP"], ["ja", "en"])
        self.assertEqual(result, "ja")

    def test_no_match_returns_none(self):
        self.assertIsNone(negotiate_language(["fr"], ["en", "ja"]))

    def test_empty_accepted(self):
        self.assertIsNone(negotiate_language([], ["en"]))

    def test_empty_supported(self):
        self.assertIsNone(negotiate_language(["en"], []))


# ============================================================
# 4. 激活与上下文
# ============================================================


class ActivateLanguageTest(unittest.TestCase):

    def test_activate_valid(self):
        result = activate_language("zh_CN")
        self.assertEqual(result, "zh-hans")
        self.assertEqual(get_current_language(), "zh-hans")

    def test_activate_invalid_falls_back(self):
        # 不支持的语言：回退到默认
        result = activate_language("xyz")
        # 默认是 zh-hans（项目设置）
        self.assertIn(result, {"zh-hans", "en"})

    def test_activate_none_falls_back(self):
        result = activate_language(None)
        self.assertIn(result, {"zh-hans", "en"})

    def test_force_language_context(self):
        activate_language("zh-hans")
        self.assertEqual(get_current_language(), "zh-hans")
        with force_language("en"):
            self.assertEqual(get_current_language(), "en")
        # 退出后恢复
        self.assertEqual(get_current_language(), "zh-hans")


# ============================================================
# 5. 多源探测（mock request）
# ============================================================


class DetectLanguageTest(unittest.TestCase):

    def setUp(self):
        # 重置后端
        reset_translation_backend(CacheTranslationBackend())
        # 关闭所有激活
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def tearDown(self):
        reset_translation_backend(CacheTranslationBackend())
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def _make_request(self, **overrides):
        """构造 mock request"""
        meta = overrides.pop("META", {})
        get = overrides.pop("GET", {})
        cookies = overrides.pop("COOKIES", {})
        req = MagicMock()
        req.META = meta
        req.GET = get
        req.COOKIES = cookies
        req.query_params = get  # DRF
        if "user" in overrides:
            req.user = overrides["user"]
        if "tenant" in overrides:
            req.tenant = overrides["tenant"]
        return req

    def test_detect_from_header(self):
        from framework.i18n.core import detect_language
        req = self._make_request(META={"HTTP_ACCEPT_LANGUAGE": "en-US,zh-CN;q=0.5"})
        self.assertEqual(detect_language(req), "en")

    def test_detect_from_query(self):
        from framework.i18n.core import detect_language
        req = self._make_request(GET={"lang": "en"})
        self.assertEqual(detect_language(req), "en")

    def test_detect_from_cookie(self):
        from framework.i18n.core import detect_language
        req = self._make_request(COOKIES={"django_language": "en"})
        self.assertEqual(detect_language(req), "en")

    def test_detect_from_user(self):
        from framework.i18n.core import detect_language
        user = MagicMock()
        user.is_authenticated = True
        user.language = "en"
        req = self._make_request(user=user)
        self.assertEqual(detect_language(req), "en")

    def test_detect_from_tenant(self):
        from framework.i18n.core import detect_language
        tenant = MagicMock()
        tenant.default_language = "en"
        req = self._make_request(tenant=tenant)
        self.assertEqual(detect_language(req), "en")

    def test_priority_header_over_query(self):
        """Header 优先级高于 Query"""
        from framework.i18n.core import detect_language, _get_detector_order
        # 默认顺序是 header, query, cookie, user, tenant, default
        order = _get_detector_order()
        self.assertEqual(order[0], "header")
        req = self._make_request(
            META={"HTTP_ACCEPT_LANGUAGE": "en"},
            GET={"lang": "zh-hans"},
        )
        self.assertEqual(detect_language(req), "en")

    def test_unsupported_falls_through(self):
        from framework.i18n.core import detect_language
        req = self._make_request(
            META={"HTTP_ACCEPT_LANGUAGE": "xyz"},
            GET={"lang": "en"},
        )
        self.assertEqual(detect_language(req), "en")

    def test_no_request_returns_default(self):
        from framework.i18n.core import detect_language
        result = detect_language(None)
        self.assertIn(result, {"zh-hans", "en"})


# ============================================================
# 6. 翻译函数
# ============================================================


class TranslationFunctionTest(unittest.TestCase):

    def setUp(self):
        # 显式重置后端实例 + 清缓存，确保隔离
        backend = CacheTranslationBackend()
        backend.clear_cache()
        reset_translation_backend(backend)
        register_translation("zh-hans", "test.hello", "你好")
        register_translation("en", "test.hello", "Hello")
        register_translation("zh-hans", "test.bye", "再见")
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def tearDown(self):
        # 清理注册的 key + 重置后端
        unregister_translation("test.hello")
        unregister_translation("test.bye")
        reset_translation_backend(CacheTranslationBackend())
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def test_t_returns_translation(self):
        activate_language("zh-hans")
        self.assertEqual(t("test.hello", "fallback"), "你好")
        activate_language("en")
        self.assertEqual(t("test.hello", "fallback"), "Hello")

    def test_t_falls_back_to_default(self):
        # 显式传 lang 强制走 fr 分支
        self.assertEqual(t("test.hello", "Hi", lang="fr"), "Hi")

    def test_t_falls_back_to_key(self):
        # 显式传 lang 强制走 fr 分支且无 default
        self.assertEqual(t("test.hello", lang="fr"), "test.hello")

    def test_t_with_explicit_lang(self):
        result = t("test.hello", lang="zh-hans")
        self.assertEqual(result, "你好")

    def test_tn_singular(self):
        activate_language("en")
        result = tn("%d item", "%d items", 1)
        self.assertIn("1", result)

    def test_tn_plural(self):
        activate_language("en")
        result = tn("%d item", "%d items", 5)
        self.assertIn("5", result)

    def test_tn_chinese_always_singular_form(self):
        activate_language("zh-hans")
        for n in [0, 1, 5]:
            result = tn("%d 个项目", "%d 个项目", n)
            self.assertIn(str(n), result)

    def test_pget(self):
        # pget 没有 .po 注册时返回 key
        result = pget("ctx", "not.registered", "fallback")
        self.assertEqual(result, "fallback")


# ============================================================
# 7. 错误本地化
# ============================================================


class LocalizeErrorTest(unittest.TestCase):

    def setUp(self):
        backend = CacheTranslationBackend()
        backend.clear_cache()
        reset_translation_backend(backend)
        # 用 value 而不是 code，避免与 localize_error 的 code 参数冲突
        register_translation("zh-hans", "err.test", "错误：{value}")
        register_translation("en", "err.test", "Error: {value}")
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def tearDown(self):
        unregister_translation("err.test")
        reset_translation_backend(CacheTranslationBackend())
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def test_with_placeholders(self):
        activate_language("zh-hans")
        result = localize_error("err.test", value=42)
        self.assertEqual(result, "错误：42")

    def test_with_placeholders_en(self):
        activate_language("en")
        result = localize_error("err.test", value=42)
        self.assertEqual(result, "Error: 42")

    def test_missing_key_returns_default(self):
        activate_language("zh-hans")
        result = localize_error("not.exist", default="默认错误")
        self.assertEqual(result, "默认错误")


# ============================================================
# 8. 数据库翻译后端
# ============================================================


class CacheBackendTest(unittest.TestCase):

    def setUp(self):
        self.backend = CacheTranslationBackend()
        # 强制清空，确保隔离
        self.backend.clear_cache()

    def test_set_and_get(self):
        self.backend.set("k1", "zh-hans", "值1")
        self.assertEqual(self.backend.get("k1", "zh-hans"), "值1")
        self.assertIsNone(self.backend.get("k1", "en"))

    def test_get_many(self):
        self.backend.set("k1", "zh-hans", "值1")
        self.backend.set("k2", "zh-hans", "值2")
        self.backend.set("k3", "en", "v3")
        result = self.backend.get_many(["k1", "k2", "k3"], "zh-hans")
        self.assertEqual(result, {"k1": "值1", "k2": "值2"})

    def test_delete_specific_lang(self):
        self.backend.set("k1", "zh-hans", "值")
        self.backend.set("k1", "en", "val")
        self.backend.delete("k1", "zh-hans")
        self.assertIsNone(self.backend.get("k1", "zh-hans"))
        self.assertEqual(self.backend.get("k1", "en"), "val")

    def test_delete_all_langs(self):
        self.backend.set("k1", "zh-hans", "值")
        self.backend.set("k1", "en", "val")
        self.backend.delete("k1")
        self.assertIsNone(self.backend.get("k1", "zh-hans"))
        self.assertIsNone(self.backend.get("k1", "en"))

    def test_list_keys(self):
        self.backend.set("k1", "zh-hans", "1")
        self.backend.set("k2", "zh-hans", "2")
        keys = self.backend.list_keys()
        self.assertIn("k1", keys)
        self.assertIn("k2", keys)

    def test_stats(self):
        self.backend.set("k1", "zh-hans", "1")
        self.backend.set("k1", "en", "1")
        self.backend.set("k2", "zh-hans", "2")
        # k2 没有 en
        zh = self.backend.stats("zh-hans")
        self.assertEqual(zh["total_keys"], 2)
        self.assertEqual(zh["translated"], 2)
        self.assertEqual(zh["coverage"], 1.0)
        en = self.backend.stats("en")
        self.assertEqual(en["total_keys"], 2)
        self.assertEqual(en["translated"], 1)
        self.assertEqual(en["coverage"], 0.5)

    def test_clear_cache(self):
        self.backend.set("k1", "zh-hans", "1")
        self.backend.clear_cache()
        self.assertIsNone(self.backend.get("k1", "zh-hans"))


# ============================================================
# 9. 翻译统计
# ============================================================


class GetTranslationStatsTest(unittest.TestCase):

    def setUp(self):
        backend = CacheTranslationBackend()
        backend.clear_cache()
        reset_translation_backend(backend)
        register_translation("zh-hans", "k1", "1")
        register_translation("zh-hans", "k2", "2")
        register_translation("en", "k1", "1")
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def tearDown(self):
        unregister_translation("k1")
        unregister_translation("k2")
        reset_translation_backend(CacheTranslationBackend())
        from django.utils import translation as _tr
        _tr.deactivate_all()

    def tearDown(self):
        reset_translation_backend(CacheTranslationBackend())

    def test_stats_zh(self):
        stats = get_translation_stats("zh-hans")
        self.assertEqual(stats["total_keys"], 2)
        self.assertEqual(stats["translated"], 2)

    def test_stats_en(self):
        stats = get_translation_stats("en")
        self.assertEqual(stats["total_keys"], 2)
        self.assertEqual(stats["translated"], 1)
        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["coverage"], 0.5)


# ============================================================
# 10. 异常
# ============================================================


class ExceptionsTest(unittest.TestCase):

    def test_unsupported_language_error(self):
        from framework.i18n.exceptions import UnsupportedLanguageError
        err = UnsupportedLanguageError("xyz", ["en", "zh-hans"])
        self.assertIn("xyz", str(err))
        self.assertIn("en", str(err))

    def test_translation_not_found(self):
        from framework.i18n.exceptions import TranslationNotFoundError
        err = TranslationNotFoundError("k1", "en")
        self.assertIn("k1", str(err))
        self.assertIn("en", str(err))

    def test_i18n_error_is_base(self):
        from framework.i18n.exceptions import UnsupportedLanguageError
        self.assertTrue(issubclass(UnsupportedLanguageError, I18nError))


if __name__ == "__main__":
    unittest.main()
