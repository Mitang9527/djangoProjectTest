# sync-init: skip
"""
i18n 异常体系
=============
"""
from __future__ import annotations


class I18nError(Exception):
    """i18n 模块所有异常的基类"""


class UnsupportedLanguageError(I18nError):
    """请求的语言不在支持列表"""

    def __init__(self, lang: str, supported: list[str] | None = None):
        self.lang = lang
        self.supported = supported or []
        msg = f"Unsupported language: {lang!r}"
        if self.supported:
            msg += f" (supported: {self.supported})"
        super().__init__(msg)


class TranslationNotFoundError(I18nError):
    """数据库翻译 key 找不到，且未提供 fallback"""

    def __init__(self, key: str, lang: str):
        self.key = key
        self.lang = lang
        super().__init__(f"Translation key {key!r} not found for language {lang!r}")
