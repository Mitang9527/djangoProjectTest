# sync-init: skip
"""
i18n 工具包的 ORM 模型（可选）
==============================

只在使用 ORMTranslationBackend 时需要。提供：

- Translation：键值翻译存储
- TranslationNamespace：命名空间（便于按模块组织）

使用方式
--------

``INSTALLED_APPS += ["utils.i18n"]`` 即可让 makemigrations 识别。
然后 ``python manage.py migrate utils_i18n``。
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class TranslationNamespace(models.Model):
    """翻译命名空间（如 'common' / 'user' / 'order'）"""

    name = models.CharField(_("命名空间"), max_length=64, unique=True)
    description = models.CharField(_("描述"), max_length=255, blank=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("翻译命名空间")
        verbose_name_plural = _("翻译命名空间")
        app_label = "utils_i18n"

    def __str__(self) -> str:
        return self.name


class Translation(models.Model):
    """动态翻译条目（运营/租户可改文案）"""

    key = models.CharField(_("翻译键"), max_length=255, db_index=True)
    lang = models.CharField(_("语言"), max_length=16, db_index=True)
    value = models.TextField(_("翻译值"))
    namespace = models.ForeignKey(
        TranslationNamespace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="translations",
        verbose_name=_("命名空间"),
    )
    is_active = models.BooleanField(_("启用"), default=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = _("翻译条目")
        verbose_name_plural = _("翻译条目")
        app_label = "utils_i18n"
        unique_together = [("key", "lang")]
        indexes = [
            models.Index(fields=["lang", "is_active"]),
            models.Index(fields=["namespace", "lang"]),
        ]

    def __str__(self) -> str:
        return f"[{self.lang}] {self.key}"
