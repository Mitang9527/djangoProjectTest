# sync-init: skip
"""i18n 核心：语言代码规范化 / Accept-Language 解析协商 / 五级探测(Header-Query-Cookie-User-Tenant-Default) / 激活切换 / 翻译函数(t,tn,lazy_t) / 错误本地化 / 租户默认语言。

依赖均项目既有：django.utils.translation / django.conf.settings / framework.translations（数据库翻译，懒加载）。
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
    """规范化语言代码（小写、_ 转 -、别名映射；未知语言透传），如 zh_CN → zh-hans。"""
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


_ACCEPT_LANG_RE = re.compile(r"([a-zA-Z\-]+)\s*(?:;q=([\d.]+))?", re.IGNORECASE)


def parse_accept_language(header: str | None) -> list[tuple[str, float]]:
    """解析 Accept-Language Header，返回按 q 降序的 (lang, q) 列表（保留原大小写，下游会规范化）。"""
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
    """从客户端声明列表与支持列表协商最佳匹配：① 完全匹配（双方先规范化）② 退化主语言（zh-* → zh-hans）。"""
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


# 探测顺序与各源参数名（可用 settings.I18N_DETECTORS / I18N_PARAMS 覆盖）
_DEFAULT_DETECTORS = ("header", "query", "cookie", "user", "tenant", "default")
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
    """按 I18N_DETECTORS 优先级探测，返回第一个匹配且受支持的语言；都没有则回退 settings.LANGUAGE_CODE。"""
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


def activate_language(lang: str | None) -> str:
    """激活指定语言并返回规范化代码；不支持时回退默认语言。"""
    norm = normalize_language_code(lang) if lang else None
    if norm and is_supported_language(norm):
        translation.activate(norm)
        return norm
    # 不支持：回退到默认
    fallback = _extract_from_default() or "en"
    translation.activate(fallback)
    return fallback


def activate_for_request(request) -> str:
    """探测并激活请求语言，同时挂到 request.LANGUAGE_CODE / request.api_language；返回最终语言代码。"""
    lang = detect_language(request)
    final = activate_language(lang)
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
    """上下文管理器：临时切换语言，退出时自动恢复。"""
    old = translation.get_language()
    final = activate_language(lang)
    try:
        yield final
    finally:
        if old:
            translation.activate(old)
        else:
            translation.deactivate_all()


def t(key: str, default: str | None = None, lang: str | None = None) -> str:
    """即时翻译。优先级：显式 lang > 当前激活语言 > 数据库翻译 > default > key 本身。

    依次尝试 Django gettext（.po/.mo）→ 数据库翻译（framework.translations）→ 兜底。
    """
    target = lang or get_current_language()

    try:
        result = translation.gettext(key)
        if result and result != key:
            return result
    except Exception as e:
        logger.debug("Django gettext failed for %r: %s", key, e)

    try:
        # 延迟导入避免循环依赖
        from .translations import get_translation_backend
        backend = get_translation_backend()
        result = backend.get(key, target)
        if result:
            return result
    except Exception as e:
        logger.debug("DB translation failed for %r/%s: %s", key, target, e)

    return default if default is not None else key


def tn(
    singular: str,
    plural: str,
    count: int,
    default: str | None = None,
    lang: str | None = None,
) -> str:
    """复数形式翻译（Django ngettext 不自动替换 %d，需手动格式化；数据库翻译暂不支持复数）。"""
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


def localize_error(
    code: str,
    default: str | None = None,
    lang: str | None = None,
    **params: Any,
) -> str:
    """翻译错误码为本地化消息，支持占位符：str.format 风格 {name}（推荐）与 % 风格 %(name)s。"""
    msg = t(code, default=default, lang=lang)
    if params:
        # 优先 str.format 风格（{key}）
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


def get_tenant_default_language(tenant=None) -> str | None:
    """获取租户默认语言（无租户则返回 None）"""
    if tenant is None:
        return None
    raw = getattr(tenant, "default_language", None) or getattr(tenant, "language", None)
    if not raw:
        return None
    norm = normalize_language_code(raw)
    return norm if is_supported_language(norm) else None
