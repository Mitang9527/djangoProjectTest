#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sync_init 单元测试
===================

使用 ``tempfile`` 构造临时包目录，覆盖：

- AST 解析：单名字 / 多名字 / __all__ / skip 标记 / 语法错误
- 扫描：递归 / 忽略目录 / 跳过 __init__.py
- 生成：import 风格 / name 风格 / 空包
- 合并：保留 docstring + 追加新 import / 已有 __all__ 不丢
- CLI：--check / --dry-run / --diff / --write
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# 确保可以 import 目标脚本
SCRIPT_PATH = Path(__file__).resolve().parent / "sync_init.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))
import sync_init  # noqa: E402


class TempPackage:
    """临时包目录上下文管理器"""

    def __init__(self, layout: dict):
        """
        Args:
            layout: {相对路径: 文件内容}，路径以 ``__init__.py`` 结尾表示要建 init
        """
        self.layout = layout
        self.tmpdir: Path = None  # type: ignore

    def __enter__(self) -> Path:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_init_test_"))
        for rel, content in self.layout.items():
            p = self.tmpdir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(content), encoding="utf-8")
        return self.tmpdir

    def __exit__(self, exc_type, exc_val, exc_tb):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------
# AST 解析
# ----------------------------------------------------------------------

class ExtractSymbolsTest(unittest.TestCase):

    def test_single_function(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": """
                def hello():
                    pass
            """,
        }) as pkg:
            sym = sync_init.extract_symbols(pkg / "mypkg" / "a.py")
            self.assertEqual(sym.effective_names, ["hello"])
            self.assertFalse(sym.has_all)
            self.assertIsNone(sym.syntax_error)

    def test_multiple_top_level(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": '''
                CONST = 1
                _PRIVATE = 2

                class Foo:
                    pass

                async def bar():
                    pass

                def _hidden():
                    pass
            ''',
        }) as pkg:
            sym = sync_init.extract_symbols(pkg / "mypkg" / "a.py")
            self.assertEqual(sym.effective_names, ["CONST", "Foo", "bar"])
            self.assertFalse(sym.has_all)

    def test_all_overrides(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": '''
                __all__ = ["A", "B"]

                def A(): pass
                def B(): pass
                def C(): pass
            ''',
        }) as pkg:
            sym = sync_init.extract_symbols(pkg / "mypkg" / "a.py")
            self.assertTrue(sym.has_all)
            self.assertEqual(sym.effective_names, ["A", "B"])

    def test_skip_marker(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "# sync-init: skip\ndef should_not_appear():\n    pass\n",
        }) as pkg:
            sym = sync_init.extract_symbols(pkg / "mypkg" / "a.py")
            self.assertTrue(sym.skipped)
            self.assertEqual(sym.effective_names, [])

    def test_syntax_error_caught(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/bad.py": "def broken(:\n",
        }) as pkg:
            sym = sync_init.extract_symbols(pkg / "mypkg" / "bad.py")
            self.assertIsNotNone(sym.syntax_error)
            self.assertIn("line", sym.syntax_error)

    def test_underscore_filtered(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": '''
                def public_fn(): pass
                def _private_fn(): pass
                class _PrivateCls: pass
            ''',
        }) as pkg:
            sym = sync_init.extract_symbols(pkg / "mypkg" / "a.py")
            self.assertEqual(sym.effective_names, ["public_fn"])


# ----------------------------------------------------------------------
# 扫描
# ----------------------------------------------------------------------

class ScanPackageTest(unittest.TestCase):

    def test_scan_finds_modules(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
            "mypkg/b.py": "def y(): pass",
            "mypkg/sub/__init__.py": "",
            "mypkg/sub/c.py": "def z(): pass",
        }) as pkg:
            results = sync_init.scan_package(pkg / "mypkg", set())
            names = sorted(s.path.name for s in results)
            self.assertEqual(names, ["a.py", "b.py", "c.py"])

    def test_scan_ignores_dirs(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
            "mypkg/__pycache__/a.pyc": "x",
            "mypkg/.git/HEAD": "ref: refs/heads/main",
        }) as pkg:
            results = sync_init.scan_package(pkg / "mypkg", set())
            self.assertEqual([s.path.name for s in results], ["a.py"])

    def test_scan_skips_init(self):
        with TempPackage({
            "mypkg/__init__.py": "from .a import *",
            "mypkg/a.py": "def x(): pass",
        }) as pkg:
            results = sync_init.scan_package(pkg / "mypkg", set())
            # __init__.py 不应出现在结果
            self.assertNotIn("__init__.py", [s.path.name for s in results])


# ----------------------------------------------------------------------
# 生成
# ----------------------------------------------------------------------

class BuildInitTest(unittest.TestCase):

    def test_basic_import_style(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
            "mypkg/b.py": "class B: pass",
        }) as pkg:
            symbols = sync_init.scan_package(pkg / "mypkg", set())
            text = sync_init.build_init_content("mypkg", symbols, style="import")
            self.assertIn("from . import a, b", text)
            self.assertIn('__all__ = ["a", "b"]', text)
            self.assertIn('__version__ = "0.1.0"', text)

    def test_empty_package(self):
        with TempPackage({"mypkg/__init__.py": ""}) as pkg:
            symbols = sync_init.scan_package(pkg / "mypkg", set())
            text = sync_init.build_init_content("mypkg", symbols)
            self.assertIn("no public symbols found", text)

    def test_long_import_breaks_lines(self):
        # 制造 6 个子模块，触发多行 import
        with TempPackage({
            "mypkg/__init__.py": "",
            **{f"mypkg/m{i}.py": f"def f{i}(): pass\n" for i in range(6)},
        }) as pkg:
            symbols = sync_init.scan_package(pkg / "mypkg", set())
            text = sync_init.build_init_content("mypkg", symbols, style="import")
            self.assertIn("from . import (\n", text)
            self.assertIn("    m0,", text)

    def test_name_style_uses_module_symbol(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/auth.py": '''
                def login(): pass
                def logout(): pass
            ''',
        }) as pkg:
            symbols = sync_init.scan_package(pkg / "mypkg", set())
            text = sync_init.build_init_content("mypkg", symbols, style="name")
            self.assertIn('"auth_login"', text)
            self.assertIn('"auth_logout"', text)


# ----------------------------------------------------------------------
# 合并
# ----------------------------------------------------------------------

class MergeInitTest(unittest.TestCase):

    def test_preserves_existing_docstring(self):
        existing = textwrap.dedent('''\
            """Existing manual init — keep me!"""
            from . import legacy
        ''')
        new = textwrap.dedent('''\
            """auto-generated"""
            from . import a, b, c
        ''')
        merged, changed = sync_init.merge_existing_init(existing, new)
        self.assertTrue(changed)
        self.assertIn("Existing manual init — keep me!", merged)
        self.assertIn("from . import legacy", merged)
        # 新增的也被追加
        self.assertIn("a, b, c", merged)

    def test_preserves_legacy_imports(self):
        existing = textwrap.dedent('''\
            """x"""
            from . import a, b
        ''')
        new = textwrap.dedent('''\
            """y"""
            from . import a, c
        ''')
        merged, _ = sync_init.merge_existing_init(existing, new)
        self.assertIn("a, b", merged)
        self.assertIn("c", merged)

    def test_no_changes_returns_same(self):
        # 当现有 init 已包含 new_content 的全部 import + __all__，应原样返回
        existing = textwrap.dedent('''\
            """x"""
            from . import a
            __all__ = ["a"]
        ''')
        new = textwrap.dedent('''\
            """y"""
            from . import a
            __all__ = ["a"]
        ''')
        merged, changed = sync_init.merge_existing_init(existing, new)
        self.assertFalse(changed)
        self.assertEqual(merged, existing)

    def test_handles_syntax_error_in_existing(self):
        existing = "def broken(:\n"
        new = "from . import a\n"
        merged, changed = sync_init.merge_existing_init(existing, new)
        self.assertTrue(changed)
        self.assertEqual(merged, new)


# ----------------------------------------------------------------------
# CLI 端到端
# ----------------------------------------------------------------------

class CliTest(unittest.TestCase):

    def _run(self, *args, cwd: Path) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_check_clean(self):
        """init 已经是最新 → check exit 0"""
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
        }) as pkg:
            # 第一次 write
            self._run("mypkg", "--write", cwd=pkg)
            # 第二次 check
            r = self._run("mypkg", "--check", cwd=pkg)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_dirty(self):
        """新建一个模块但没重跑 sync → check exit 1"""
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
        }) as pkg:
            self._run("mypkg", "--write", cwd=pkg)
            # 新增模块
            (pkg / "mypkg" / "b.py").write_text("def y(): pass")
            r = self._run("mypkg", "--check", cwd=pkg)
            self.assertEqual(r.returncode, 1)
            self.assertIn("Out of sync", r.stdout)

    def test_dry_run_does_not_write(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
        }) as pkg:
            r = self._run("mypkg", "--dry-run", cwd=pkg)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("from . import a", r.stdout)
            # init 文件应仍为空（dry-run 不写）
            init_text = (pkg / "mypkg" / "__init__.py").read_text()
            self.assertEqual(init_text.strip(), "")

    def test_write_creates_init(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
            "mypkg/b.py": "class B: pass",
        }) as pkg:
            r = self._run("mypkg", "--write", cwd=pkg)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            init_text = (pkg / "mypkg" / "__init__.py").read_text(encoding="utf-8")
            self.assertIn("from . import a, b", init_text)
            self.assertIn('"a", "b"', init_text)

    def test_diff_shows_changes(self):
        with TempPackage({
            "mypkg/__init__.py": "",
            "mypkg/a.py": "def x(): pass",
        }) as pkg:
            self._run("mypkg", "--write", cwd=pkg)
            (pkg / "mypkg" / "b.py").write_text("def y(): pass")
            r = self._run("mypkg", "--diff", cwd=pkg)
            self.assertEqual(r.returncode, 0)
            self.assertIn("--- a/", r.stdout)
            self.assertIn("+++ b/", r.stdout)

    def test_force_overwrites(self):
        existing = '"""hand-written — should be replaced"""\n'
        with TempPackage({
            "mypkg/__init__.py": existing,
            "mypkg/a.py": "def x(): pass",
        }) as pkg:
            r = self._run("mypkg", "--force", cwd=pkg)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            new_text = (pkg / "mypkg" / "__init__.py").read_text(encoding="utf-8")
            self.assertNotIn("hand-written", new_text)
            self.assertIn("from . import a", new_text)

    def test_merge_preserves_existing(self):
        existing = '"""legacy doc — keep me"""\nfrom . import a\n'
        with TempPackage({
            "mypkg/__init__.py": existing,
            "mypkg/a.py": "def x(): pass",
            "mypkg/b.py": "def y(): pass",
        }) as pkg:
            r = self._run("mypkg", "--write", cwd=pkg)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            new_text = (pkg / "mypkg" / "__init__.py").read_text(encoding="utf-8")
            self.assertIn("legacy doc", new_text)
            self.assertIn("a", new_text)
            self.assertIn("b", new_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
