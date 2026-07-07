# sync-init: skip
"""
扫描代码中的 gettext 调用
==========================

``python manage.py i18n_scan`` — 扫描所有 .py 文件中的 ``_("...")`` /
``gettext_lazy("...")`` 调用，输出未翻译的 key（与现有 .po 文件 diff）。

``python manage.py i18n_scan --unused`` — 找出 .po 中存在但代码里没引用的 key
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "扫描代码中的 gettext 调用（与 .po 文件对比）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=None,
            help="扫描根目录（默认 BASE_DIR）",
        )
        parser.add_argument(
            "--po-root",
            type=str,
            default=None,
            help=".po 文件根目录（默认各 app 的 locale/ 目录）",
        )
        parser.add_argument(
            "--unused",
            action="store_true",
            help="显示 .po 中未引用的 key",
        )

    def handle(self, *args, **options):
        base = Path(options["path"] or settings.BASE_DIR)
        po_root = options["po_root"]  # 暂不实现复杂逻辑，仅做提示

        # 1. 扫描代码
        code_keys = self._scan_code(base)
        self.stdout.write(self.style.SUCCESS(f"Found {len(code_keys)} unique gettext keys in code"))

        # 2. 扫描 .po
        po_keys = self._scan_po(base) if not po_root else set()
        self.stdout.write(self.style.SUCCESS(f"Found {len(po_keys)} unique keys in .po files"))

        # 3. diff
        if options["unused"]:
            unused = po_keys - code_keys
            self.stdout.write(self.style.WARNING(f"\nUnused keys in .po ({len(unused)}):"))
            for k in sorted(unused):
                self.stdout.write(f"  {k}")
        else:
            missing = code_keys - po_keys
            self.stdout.write(self.style.WARNING(f"\nKeys in code but missing in .po ({len(missing)}):"))
            for k in sorted(missing):
                self.stdout.write(f"  {k}")

    def _scan_code(self, root: Path) -> set[str]:
        """AST 扫描所有 .py 文件中的 _ / gettext_lazy / pgettext_lazy"""
        keys: set[str] = set()
        i18n_funcs = {"_", "gettext", "gettext_lazy", "pgettext", "pgettext_lazy",
                      "ugettext", "ugettext_lazy", "ngettext", "ngettext_lazy"}
        for py in root.rglob("*.py"):
            # 跳过 venv / migrations
            if any(seg in py.parts for seg in (".venv", "migrations", "__pycache__", ".workbuddy")):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # 形式一：_("...")
                name = None
                if isinstance(func, ast.Name) and func.id in i18n_funcs:
                    name = func.id
                # 形式二：ugettext_lazy("...")
                elif isinstance(func, ast.Attribute) and func.attr in i18n_funcs:
                    name = func.attr
                if not name:
                    continue
                if not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    keys.add(first.value)
        return keys

    def _scan_po(self, root: Path) -> set[str]:
        """扫描所有 .po 中的 msgid"""
        import re
        keys: set[str] = set()
        msgid_re = re.compile(r'^msgid\s+"((?:[^"\\]|\\.)*)"', re.MULTILINE)
        for po in root.rglob("*.po"):
            if any(seg in po.parts for seg in (".venv", "__pycache__", ".workbuddy")):
                continue
            try:
                content = po.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for m in msgid_re.finditer(content):
                key = m.group(1)
                if key:  # 跳过空 msgid（PO header）
                    keys.add(key)
        return keys
