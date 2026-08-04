# sync-init: skip
"""
i18n 核心实现
=============

- 语言代码规范化
- Accept-Language 解析与协商
- 多源语言探测（Header / Query / Cookie / User / Tenant / Default 五级）
- 激活与上下文切换
- 翻译函数（t / tn / lazy_t / lazy_tn）
- 错误消息本地化
- 租户默认语言

依赖（均项目既有）：
- django.utils.translation
- django.conf.settings
- framework.translations（数据库驱动翻译，按需懒加载）
"""
from __future__ import annotations

import contextlib
import logging
import re
from typing import Any, Iterable, Iterator, Optional

from django.conf import settings
from django.utils import translation
from django.utils.functional import Promise, lazy

from .exceptions import I18nError, UnsupportedLanguageError

logger = logging.getLogger(__name__)


# ============================================================
# 1. 语言代码处理
# ============================================================

# 常见别名到规范代码的映射
_LANGUAGE_ALIASES = {
    "zh": "zh-hans",
    "zh-cn": "zh-hans",
    "zh_cn": "zh-hans",
    "zh-hans": "zh-hans",
    "zh-hans-cn": "zh-hans",
    "zh-hant": "zh-hant",
    "zh-tw": "zh-hant",
    "zh_hk": "zh-hant",
    "zh-hk": "zh-hant",
    "en": "en",
    "en-us": "en",
    "en_gb": "en",
    "en-uk": "en",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "fr": "fr",
    "fr-fr": "fr",
    "de": "de",
    "de-de": "de",
    "es": "es",
    "ru": "ru",
    "en-gb": "en",
    "en-uk": "en",
}


def normalize_language_code(lang: str | None) -> str | None:
    """
    规范化语言代码。

    >>> normalize_language_code("zh_CN")
    'zh-hans'
    >>> normalize_language_code("EN")
    'en'
    >>> normalize_language_code("ja")
    'ja'  # 未知语言透传
    >>> normalize_language_code(None)
    """
    if not lang:
        return None
    key = lang.strip().lower().replace("_", "-")
    return _LANGUAGE_ALIASES.get(key, key)


def get_supported_languages() -> list[tuple[str, str]]:
    """返回 Django settings.LANGUAGES 列表 [(code, name), ...]"""
    return list(getattr(settings, "LANGUAGES", [("en", "English")]))


def is_supported_language(lang: str | None) -> bool:
    """判断语言是否在 settings.LANGUAGES 中（先规范化）"""
    if not lang:
        return False
    norm = normalize_language_code(lang)
    supported = {code for code, _ in get_supported_languages()}
    return norm in supported


# ============================================================
# 2. Accept-Language 解析
# ============================================================

_ACCEPT_LANG_RE = re.compile(r"([a-zA-Z\-]+)\s*(?:;q=([\d.]+))?", re.IGNORECASE)


def parse_accept_language(header: str | None) -> list[tuple[str, float]]:
    """
    解析 Accept-Language Header，返回按 q 值降序的 (lang, q) 列表。

    保留原始大小写（下游 ``negotiate_language`` 会做规范化）。

    >>> parse_accept_language("zh-CN,en-US;q=0.8,ja;q=0.5")
    [('zh-CN', 1.0), ('en-US', 0.8), ('ja', 0.5)]
    >>> parse_accept_language("")
    []
    """
    if not header:
        return []
    out: list[tuple[str, float]] = []
    for m in _ACCEPT_LANG_RE.finditer(header):
        lang = m.group(1)
        q_raw = m.group(2)
        try:
            q = float(q_raw) if q_raw else 1.0
        except (TypeError, ValueError):
            q = 1.0
        out.append((lang, q))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def negotiate_language(
    accepted: Iterable[str],
    supported: Iterable[str] | None = None,
) -> str | None:
    """
    从客户端声明的语言列表与系统支持的语言列表中，协商出最佳匹配。

    1. 完全匹配（双方都先规范化）
    2. 退化到主语言（zh-* → zh-hans，如果主语言在支持集中）
    """
    supp = list(supported) if supported is not None else [
        code for code, _ in get_supported_languages()
    ]
    supp_norm_set = {normalize_language_code(s) for s in supp if s}
    supp_norm_set.discard(None)

    if not supp_norm_set:
        return None

    # 按 q 值降序遍历 accepted
    for raw in accepted:
        norm = normalize_language_code(raw)
        if norm and norm in supp_norm_set:
            return norm
        # 主语言兜底（如 zh-TW → zh-hans 如果后者在支持集）
        if norm and "-" in norm:
            primary = norm.split("-")[0]
            if primary in supp_norm_set:
                return primary

    return None


# ============================================================
# 3. 多源语言探测（Header / Query / Cookie / User / Tenant / Default）
# ============================================================

# 探测顺序：从最优先到最末
# 可在 settings 中通过 I18N_DETECTORS 配置覆盖顺序
_DEFAULT_DETECTORS = ("header", "query", "cookie", "user", "tenant", "default")

# 各源的参数名（也可在 settings 中覆盖）
_DEFAULT_PARAMS = {
    "header_name": "HTTP_ACCEPT_LANGUAGE",
    "query_name": "lang",
    "cookie_name": "django_language",
    "user_attr": "language",
    "tenant_attr": "default_language",
}


def _get_params() -> dict[str, str]:
    """合并 settings.I18N_PARAMS 与默认参数"""
    custom = getattr(settings, "I18N_PARAMS", {}) or {}
    return {**_DEFAULT_PARAMS, **custom}


def _get_detector_order() -> tuple[str, ...]:
    return tuple(getattr(settings, "I18N_DETECTORS", _DEFAULT_DETECTORS))


def _extract_from_header(request) -> str | None:
    """从 Accept-Language Header 提取"""
    params = _get_params()
    raw = request.META.get(params["header_name"], "")
    parsed = parse_accept_language(raw)
    if not parsed:
        return None
    supported = [code for code, _ in get_supported_languages()]
    # 构造 accepted 列表（保持 q 顺序）
    accepted = [lang for lang, _ in parsed]
    return negotiate_language(accepted, supported)


def _extract_from_query(request) -> str | None:
    """从 ?lang=xx 提取"""
    params = _get_params()
    raw = request.GET.get(params["query_name"]) or request.query_params.get(
        params["query_name"]
    ) if hasattr(request, "query_params") else None
    if raw is None and hasattr(request, "GET"):
        raw = request.GET.get(params["query_name"])
    if not raw:
        return None
    norm = normalize_language_code(raw)
    return norm if is_supported_language(norm) else None


def _extract_from_cookie(request) -> str | None:
    """从 cookie 提取"""
    params = _get_params()
    raw = request.COOKIES.get(params["cookie_name"])
    if not raw:
        return None
    norm = normalize_language_code(raw)
    return norm if is_supported_language(norm) else None


def _extract_from_user(request) -> str | None:
    """从已登录用户的 language 字段提取"""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None
    params = _get_params()
    raw = getattr(user, params["user_attr"], None)
    if not raw:
        return None
    norm = normalize_language_code(raw)
    return norm if is_supported_language(norm) else None


def _extract_from_tenant(request) -> str | None:
    """从 request.tenant.default_language 提取"""
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return None
    params = _get_params()
    raw = getattr(tenant, params["tenant_attr"], None)
    if not raw:
        return None
    norm = normalize_language_code(raw)
    return norm if is_supported_language(norm) else None


def _extract_from_default() -> str | None:
    """从 settings.LANGUAGE_CODE 提取"""
    raw = getattr(settings, "LANGUAGE_CODE", "en")
    return normalize_language_code(raw)


_EXTRACTORS = {
    "header": _extract_from_header,
    "query": _extract_from_query,
    "cookie": _extract_from_cookie,
    "user": _extract_from_user,
    "tenant": _extract_from_tenant,
    "default": lambda req: _extract_from_default(),
}


def detect_language(request=None) -> str | None:
    """
    按 I18N_DETECTORS 配置的优先级探测语言。

    返回第一个匹配且支持的语言代码；都没有则返回 settings.LANGUAGE_CODE。
    """
    order = _get_detector_order()
    for source in order:
        extractor = _EXTRACTORS.get(source)
        if not extractor:
            continue
        try:
            lang = extractor(request)
        except Exception as e:  # 单个源失败不影响整体
            logger.debug("Language detector %r failed: %s", source, e)
            continue
        if lang and is_supported_language(lang):
            return lang
    return _extract_from_default()


# ============================================================
# 4. 激活与上下文切换
# ============================================================


def activate_language(lang: str | None) -> str:
    """
    激活指定语言。返回规范化的语言代码。

    >>> activate_language("zh_CN")
    'zh-hans'
    """
    norm = normalize_language_code(lang) if lang else None
    if norm and is_supported_language(norm):
        translation.activate(norm)
        return norm
    # 不支持：回退到默认
    fallback = _extract_from_default() or "en"
    translation.activate(fallback)
    return fallback


def activate_for_request(request) -> str:
    """
    探测并激活请求对应的语言。返回最终激活的语言代码。
    还会把语言挂到 request 上：request.LANGUAGE_CODE / request.api_language。
    """
    lang = detect_language(request)
    final = activate_language(lang)
    # 挂到 request
    try:
        request.LANGUAGE_CODE = final
    except Exception:
        pass
    try:
        request.api_language = final
    except Exception:
        pass
    return final


def get_current_language() -> str:
    """获取当前线程激活的语言代码"""
    return translation.get_language() or _extract_from_default() or "en"


@contextlib.contextmanager
def force_language(lang: str) -> Iterator[str]:
    """
    上下文管理器：临时切换语言，退出时自动恢复。

    >>> with force_language("en"):
    ...     print(t("common.save_success"))
    """
    old = translation.get_language()
    final = activate_language(lang)
    try:
        yield final
    finally:
        if old:
            translation.activate(old)
        else:
            translation.deactivate_all()


# ============================================================
# 5. 翻译函数
# ============================================================


def t(key: str, default: str | None = None, lang: str | None = None) -> str:
    """
    即时翻译。

    优先级：
    1. 显式 lang 参数指定的语言
    2. 当前激活语言
    3. 数据库翻译（framework.translations）
    4. default 参数
    5. key 本身
    """
    target = lang or get_current_language()

    # 1) Django 内置 _() 翻译（从 .po / .mo 加载）
    try:
        result = translation.gettext(key)
        if result and result != key:
            return result
    except Exception as e:
        logger.debug("Django gettext failed for %r: %s", key, e)

    # 2) 数据库动态翻译
    try:
        # 延迟导入避免循环依赖
        from .translations import get_translation_backend
        backend = get_translation_backend()
        result = backend.get(key, target)
        if result:
            return result
    except Exception as e:
        logger.debug("DB translation failed for %r/%s: %s", key, target, e)

    # 3) 兜底
    return default if default is not None else key


def tn(
    singular: str,
    plural: str,
    count: int,
    default: str | None = None,
    lang: str | None = None,
) -> str:
    """
    复数形式翻译。

    >>> tn("1 item", "%d items", 1)
    '1 item'
    >>> tn("1 item", "%d items", 5)
    '5 items'
    """
    target = lang or get_current_language()
    try:
        template = translation.ngettext(singular, plural, count)
        if template and template != singular:
            # Django ngettext 不会自动替换 %d，需要手动格式化
            try:
                return template % count
            except (TypeError, ValueError):
                return template
    except Exception as e:
        logger.debug("Django ngettext failed: %s", e)

    # 数据库动态翻译暂不支持复数
    return (default if default is not None else (singular if count == 1 else plural)) % count


def pget(context: str, key: str, default: str | None = None) -> str:
    """带上下文的翻译（pgettext）"""
    try:
        result = translation.pgettext(context, key)
        if result and result != key:
            return result
    except Exception as e:
        logger.debug("Django pgettext failed: %s", e)
    return default if default is not None else key


def nget(context: str, singular: str, plural: str, count: int) -> str:
    """带上下文的复数翻译（npgettext）"""
    try:
        return translation.npgettext(context, singular, plural, count)
    except Exception:
        return (singular if count == 1 else plural) % count


# 懒翻译代理：用于类属性/参数默认值场景
def lazy_t(key: str, default: str | None = None) -> Promise:
    """返回懒翻译代理（适用于 model verbose_name 等场景）"""
    return lazy(lambda: t(key, default), str)()


def lazy_tn(singular: str, plural: str, count: int) -> Promise:
    """返回懒复数翻译代理"""
    return lazy(lambda: tn(singular, plural, count), str)()


# ============================================================
# 6. 错误消息本地化
# ============================================================


def localize_error(
    code: str,
    default: str | None = None,
    lang: str | None = None,
    **params: Any,
) -> str:
    """
    翻译错误码为本地化消息，可附带占位符参数。

    支持两种占位符语法：
    - str.format 风格：``"错误：{name}"``（推荐）
    - % 风格：``"错误：%(name)s"``

    >>> localize_error("user.email_exists")
    '邮箱已存在'
    >>> localize_error("order.amount_invalid", amount=100)
    '金额 100 无效'
    """
    msg = t(code, default=default, lang=lang)
    if params:
        # 优先用 str.format 风格（{key}）
        if "{" in msg and "}" in msg:
            try:
                return msg.format(**params)
            except (KeyError, IndexError, ValueError) as e:
                logger.warning("localize_error format failed for %r: %s", code, e)
                return msg
        # 退化到 % 风格（%(key)s）
        try:
            return msg % params
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("localize_error placeholder mismatch for %r: %s", code, e)
            return msg
    return msg


# ============================================================
# 7. 租户默认语言
# ============================================================


def get_tenant_default_language(tenant=None) -> str | None:
    """获取租户默认语言（无租户则返回 None）"""
    if tenant is None:
        return None
    raw = getattr(tenant, "default_language", None) or getattr(tenant, "language", None)
    if not raw:
        return None
    norm = normalize_language_code(raw)
    return norm if is_supported_language(norm) else None
