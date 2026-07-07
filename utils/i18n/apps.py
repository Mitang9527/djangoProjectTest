# sync-init: skip
"""
utils.i18n AppConfig
====================

注册为 ``utils_i18n`` 标签（避免与 django.utils.translation 冲突）。
"""
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class I18nConfig(AppConfig):
    name = "utils.i18n"
    verbose_name = _("i18n 工具包")
    label = "utils_i18n"  # 显式指定 label，避免与 django 内置冲突
    default_auto_field = "django.db.models.BigAutoField"
