#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sync_init.py
============

自动生成 / 同步 Python 包的 ``__init__.py`` 公开符号导入。

**核心特性**：

1. **AST 解析，不真 import** — 不依赖 Django / 业务库，CI 友好
2. **支持 ``__all__``** — 优先尊重文件自带的 ``__all__`` 声明
3. **支持 skip 标记** — 文件首行注释 ``# sync-init: skip`` 跳过扫描
4. **多模式** — ``--dry-run`` / ``--check`` / ``--diff`` / ``--write`` / ``--force``
5. **智能合并** — 已有 ``__init__.py`` 的非空内容保留 docstring，添加新符号
6. **跳过手工定制的 init** — 已有 docstring + 业务逻辑（如 ``cache/__init__.py`` 调
   ``register_warmup``）不会被覆盖；只追加缺失的符号

**典型用法**：

.. code-block:: bash

    # 仅查看会改什么（CI 友好）
    python scripts/sync_init.py utils --check

    # 显示 diff
    python scripts/sync_init.py utils --diff

    # 真正写盘（已存在的 init 只追加，不覆盖）
    python scripts/sync_init.py utils --write

    # 强制重写（会丢失手工内容，请备份！）
    python scripts/sync_init.py utils --force

**作者**：WorkBuddy
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

# ----------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------

SKIP_MARKER = "# sync-init: skip"  # 文件首行标记
DEFAULT_IGNORE = {"__pycache__", ".git", ".idea", ".vscode", "node_modules", ".workbuddy"}
DEFAULT_EXTS = {".py"}

# 公开符号检测的 AST 节点类型
# 注意：ast.TypeAlias 是 Python 3.12+ 才有的，低版本需 getattr 兜底
_TYPE_ALIAS = getattr(ast, "TypeAlias", None)
_TOP_LEVEL_NODE_TYPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
)
if _TYPE_ALIAS is not None:
    _TOP_LEVEL_NODE_TYPES = _TOP_LEVEL_NODE_TYPES + (_TYPE_ALIAS,)

# 哪些名字是公开的：默认无下划线前缀即公开
def _is_public(name: str) -> bool:
    return bool(name) and not name.startswith("_")


# ----------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------

@dataclass
class ModuleSymbols:
    """单个 Python 文件提取出的公开符号"""

    path: Path                    # 源文件路径
    public_names: List[str] = field(default_factory=list)  # 公开符号（保序）
    has_all: bool = False         # 是否显式声明了 __all__
    all_names: List[str] = field(default_factory=list)     # __all__ 内容
    module_doc: Optional[str] = None  # 模块 docstring
    syntax_error: Optional[str] = None  # 解析失败时的错误信息
    skipped: bool = False         # 是否因 skip 标记被跳过

    @property
    def effective_names(self) -> List[str]:
        """最终对外暴露的符号列表（__all__ 优先）"""
        if self.has_all:
            return list(self.all_names)
        return list(self.public_names)


# ----------------------------------------------------------------------
# AST 解析
# ----------------------------------------------------------------------

class SymbolExtractor(ast.NodeVisitor):
    """遍历 AST，提取顶层公开符号与 __all__"""

    def __init__(self) -> None:
        self.public_names: List[str] = []
        self.seen: Set[str] = set()
        self.has_all = False
        self.all_names: List[str] = []
        self.module_doc: Optional[str] = None

    def visit_Module(self, node: ast.Module) -> None:
        self.module_doc = ast.get_docstring(node)
        self.generic_visit(node)

    # 显式 __all__ 优先
    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                self.has_all = True
                self.all_names = self._extract_str_list(node.value)
                return  # __all__ 已解析，结束
        self._maybe_record_assign(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._maybe_record_assign(node)

    def visit_TypeAlias(self, node: ast.TypeAlias) -> None:  # py3.12+
        self._record(node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node.name)

    # ---------- 内部辅助 ----------

    def _maybe_record_assign(self, node) -> None:
        """记录被赋值的顶层常量名（忽略 _xxx 与 from-import）"""
        for target in getattr(node, "targets", []):
            if isinstance(target, ast.Name):
                if _is_public(target.id):
                    self._record(target.id)

    def _record(self, name: str) -> None:
        if not _is_public(name):
            return
        if name in self.seen:
            return
        self.seen.add(name)
        self.public_names.append(name)

    @staticmethod
    def _extract_str_list(node) -> List[str]:
        """从 ``__all__ = [...]`` / ``__all__ = (...)`` 提取字符串列表"""
        if isinstance(node, (ast.List, ast.Tuple)):
            names: List[str] = []
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.append(elt.value)
            return names
        return []


def extract_symbols(path: Path) -> ModuleSymbols:
    """解析单个 .py 文件，返回其公开符号"""
    sym = ModuleSymbols(path=path)
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        sym.syntax_error = f"read error: {exc}"
        return sym

    # 文件首行 skip 标记
    first_line = src.splitlines()[0] if src else ""
    if SKIP_MARKER in first_line:
        sym.skipped = True
        return sym

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        sym.syntax_error = f"line {exc.lineno}: {exc.msg}"
        return sym

    extractor = SymbolExtractor()
    extractor.visit(tree)

    sym.public_names = extractor.public_names
    sym.has_all = extractor.has_all
    sym.all_names = extractor.all_names
    sym.module_doc = extractor.module_doc
    return sym


# ----------------------------------------------------------------------
# 包扫描
# ----------------------------------------------------------------------

def iter_python_files(root: Path, ignore: Set[str]) -> Iterable[Path]:
    """递归遍历 root 下所有 .py 文件（按文件名排序，便于 diff 稳定）"""
    for dirpath, dirnames, filenames in os.walk(root):
        # 剪枝：过滤忽略目录
        dirnames[:] = sorted(d for d in dirnames if d not in ignore and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            ext = os.path.splitext(fn)[1]
            if ext not in DEFAULT_EXTS:
                continue
            yield Path(dirpath) / fn


def scan_package(pkg_root: Path, ignore: Set[str]) -> List[ModuleSymbols]:
    """扫描包目录下所有 Python 文件（不含 pkg_root 自身的 __init__.py）"""
    results: List[ModuleSymbols] = []
    for p in iter_python_files(pkg_root, ignore):
        if p.name == "__init__.py":
            continue
        results.append(extract_symbols(p))
    return results


# ----------------------------------------------------------------------
# __init__.py 生成
# ----------------------------------------------------------------------

HEADER_TEMPLATE = '''\
"""
{package_name} — auto-generated public API
==========================================

由 ``scripts/sync_init.py`` 自动生成。
**请勿手工编辑**，改动会被覆盖。如需添加新符号，直接在对应子模块定义即可。

要禁用某个文件的扫描：在该文件首行添加 ``# sync-init: skip``。
"""

# flake8: noqa
# isort: skip_file
'''

# 同一文件多符号时的分组：连续 4 个以上 → 换行 + 缩进
def _format_import_block(imports: List[str], group_size: int = 5) -> str:
    if not imports:
        return ""
    if len(imports) <= group_size:
        return "from . import " + ", ".join(imports) + "\n"
    inner = ",\n    ".join(imports)
    return "from . import (\n    " + inner + ",\n)\n"


def _format_all_block(names: List[str], group_size: int = 8) -> str:
    if not names:
        return ""
    if len(names) <= group_size:
        items = ", ".join(f'"{n}"' for n in names)
        return f"__all__ = [{items}]\n"
    inner = ",\n    ".join(f'"{n}"' for n in names)
    return '__all__ = [\n    "' + '",\n    "'.join(names) + '",\n]\n'


def build_init_content(
    package_name: str,
    symbols: List[ModuleSymbols],
    style: str = "import",
) -> str:
    """
    构造 __init__.py 文本。

    Args:
        package_name: 包名（用于 docstring）
        symbols: 已扫描的子模块列表（不含语法错误或被 skip 的）
        style: ``"import"`` — ``from . import xxx``；``"name"`` — ``from .xxx import *``

    Returns:
        完整的 __init__.py 字符串
    """
    parts: List[str] = [HEADER_TEMPLATE.format(package_name=package_name)]
    parts.append("\n")
    parts.append(f'__version__ = "0.1.0"\n')
    parts.append("\n")

    # 按子模块名排序（去重）
    seen: Set[str] = set()
    rows: List[Tuple[str, List[str]]] = []
    for sym in symbols:
        if sym.skipped or sym.syntax_error:
            continue
        modname = sym.path.stem
        if modname in seen:
            continue
        seen.add(modname)
        rows.append((modname, sym.effective_names))

    rows.sort(key=lambda r: r[0])

    if not rows:
        parts.append("# (no public symbols found)\n")
        return "".join(parts)

    # 收集 import 段
    if style == "import":
        names = [m for m, _ in rows]
        parts.append(_format_import_block(names))
        parts.append("\n")

    # 构造 __all__
    all_names: List[str] = []
    if style == "name":
        for mod, names_in_mod in rows:
            for n in names_in_mod:
                # 命名：module.Symbol → module_symbol
                flat = f"{mod}_{n}"
                all_names.append(flat)
        parts.append(_format_all_block(all_names))
        parts.append("\n")
    else:
        # 简单模式：__all__ = 子模块名列表
        for mod, _ in rows:
            all_names.append(mod)
        parts.append(_format_all_block(all_names))
        parts.append("\n")

    return "".join(parts)


# ----------------------------------------------------------------------
# 与现有 __init__.py 合并
# ----------------------------------------------------------------------

def _extract_all_names(source: str) -> List[str]:
    """从源文本中提取 `__all__` 列表（不解析整个文件）"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        return [
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
    return []


def _find_from_dot_imports(source: str) -> Tuple[List[str], List[Tuple[int, int]]]:
    """
    找出所有 `from . import ...` 行，返回 (模块名列表, (start_line, end_line))。

    end_line 是 1-indexed 闭区间。多个连续 from . import 块都返回。
    """
    names: List[str] = []
    blocks: List[Tuple[int, int]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names, blocks

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in (".", None):
            block_names = [a.name for a in node.names]
            names.extend(block_names)
            blocks.append((node.lineno, node.end_lineno or node.lineno))

    return names, blocks


def merge_existing_init(
    existing: str,
    new_content: str,
) -> Tuple[str, bool]:
    """
    智能合并：保留现有 docstring + 手工代码，追加新符号 + 合并 __all__。

    策略：
      1. 解析现有 init 找出 from . import 行位置
      2. 把新发现的子模块名追加到现有 import 行（或在最后追加 from . import 块）
      3. 把新发现的 __all__ 项合并到现有 __all__ 列表
      4. docstring / 其他业务代码完全不动
    """
    if not existing.strip():
        return new_content, True

    # 已有手动管理标记 → 不动
    first = existing.splitlines()[0] if existing.splitlines() else ""
    if SKIP_MARKER in first:
        return existing, False

    try:
        ast.parse(existing)
    except SyntaxError:
        return new_content, True

    # 从 new_content 提取要追加的 import / __all__
    new_imports_set, _ = _find_from_dot_imports(new_content)
    new_all = _extract_all_names(new_content)

    existing_imports_list, blocks = _find_from_dot_imports(existing)
    existing_imports_set = set(existing_imports_list)
    existing_all = _extract_all_names(existing)

    # 真正需要追加的
    to_add_imports = [n for n in new_imports_set if n not in existing_imports_set]
    to_add_all = [n for n in new_all if n not in existing_all]

    if not to_add_imports and not to_add_all:
        return existing, False  # 完全没新东西

    lines = existing.splitlines(keepends=True)

    # ---- 1) 追加 import ----
    if to_add_imports:
        if blocks:
            # 在最后一个 from . import 块后追加
            last_end = blocks[-1][1]  # 1-indexed
            insert_at = last_end  # 0-indexed = last_end
            # 选择合并到最后一个块 OR 新增一个 from . import 行
            # 简单做：新增一个独立 from . import 行
            addition = "from . import " + ", ".join(sorted(to_add_imports)) + "\n"
            lines.insert(insert_at, addition)
        else:
            # 没有现成的 from . import → 在文件末尾追加
            if not lines or not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append("\n# sync_init: auto-added\n")
            lines.append("from . import " + ", ".join(sorted(to_add_imports)) + "\n")

    # ---- 2) 追加 __all__ ----
    if to_add_all:
        # 找 __all__ 块（用行号）
        try:
            tree = ast.parse(existing)
        except SyntaxError:
            tree = ast.parse("".join(lines))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)) and node.value.elts:
                            # 在最后一个元素后插入
                            last_elt = node.value.elts[-1]
                            last_elt_end = last_elt.end_lineno or node.end_lineno or 1  # 1-indexed
                            insert_at = last_elt_end  # 0-indexed
                            addition_lines = [
                                ",\n    " + ", ".join(f'"{n}"' for n in to_add_all) + ",\n"
                            ]
                            for add_line in addition_lines:
                                lines.insert(insert_at, add_line)
                            break
                else:
                    continue
                break
        else:
            # 没找到 __all__ → 追加在文件末尾
            if not lines or not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append("\n__all__ = [" + ", ".join(f'"{n}"' for n in to_add_all) + "]\n")

    return "".join(lines), True


# ----------------------------------------------------------------------
# 统一 diff 展示
# ----------------------------------------------------------------------

def make_diff(old: str, new: str, path: str) -> str:
    """生成 unified diff 文本"""
    import difflib
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _print_summary(
    pkg_root: Path,
    symbols: List[ModuleSymbols],
    init_path: Path,
    existing: str,
) -> int:
    """打印扫描摘要"""
    def _safe(text: str) -> str:
        # 兜底：若终端编码不支持 emoji，替换为 ASCII
        try:
            text.encode(sys.stdout.encoding or "utf-8")
        except (UnicodeEncodeError, LookupError):
            text = text.encode("ascii", "replace").decode("ascii")
        return text

    print(_safe(f"[PKG] Package: {pkg_root}"))
    print(_safe(f"[FILE] Init file: {init_path}"))
    print(f"[STAT] Modules scanned: {len(symbols)}")
    skipped = [s for s in symbols if s.skipped]
    errors = [s for s in symbols if s.syntax_error]
    if skipped:
        print(_safe(f"[SKIP] Skipped: {len(skipped)}  ({', '.join(s.path.name for s in skipped[:5])}"
              + (" ..." if len(skipped) > 5 else "") + ")"))
    if errors:
        print(_safe(f"[ERR] Syntax errors: {len(errors)}"))
        for s in errors[:5]:
            print(_safe(f"   - {s.path.name}: {s.syntax_error}"))
    if existing.strip():
        print("[INFO] Existing __init__.py detected -> merge mode")
    else:
        print("[INFO] No existing __init__.py -> create mode")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync_init",
        description=textwrap.dedent(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "package",
        help="包目录路径（如 utils/）",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=None,
        help="额外忽略的目录名（可多次指定）",
    )
    parser.add_argument(
        "--style",
        choices=["import", "name"],
        default="import",
        help="导出风格：import (from . import x) / name (from .x import *)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="只检查，不写盘，CI 模式（有差异时 exit 1）")
    mode.add_argument("--dry-run", action="store_true",
                      help="显示会写什么，但不写盘")
    mode.add_argument("--diff", action="store_true",
                      help="显示 unified diff")
    mode.add_argument("--write", action="store_true",
                      help="真正写盘（默认行为）")
    mode.add_argument("--force", action="store_true",
                      help="强制覆盖（不合并，丢失手工内容）")
    parser.add_argument(
        "--init-mode",
        choices=["auto", "skip", "create"],
        default="auto",
        help=(
            "auto: 已有非空 init 则合并；空 init 则保持空；"
            "skip: 永远不动 init（仅 dry-run 报告）；"
            "create: 即便空 init 也生成（注意：会让 from utils import xxx 暴露全部子模块）"
        ),
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="静默模式")

    args = parser.parse_args(argv)

    pkg_root = Path(args.package).resolve()
    if not pkg_root.is_dir():
        print(f"❌ Not a directory: {pkg_root}", file=sys.stderr)
        return 2

    ignore = set(DEFAULT_IGNORE)
    if args.ignore:
        ignore.update(args.ignore)

    init_path = pkg_root / "__init__.py"
    existing = init_path.read_text(encoding="utf-8") if init_path.exists() else ""

    symbols = scan_package(pkg_root, ignore)
    new_content = build_init_content(pkg_root.name, symbols, style=args.style)

    if not args.quiet:
        _print_summary(pkg_root, symbols, init_path, existing)

    # 决定最终内容
    if args.init_mode == "skip":
        if not args.quiet:
            print("\n[SKIP-MODE] init_mode=skip -> no changes")
        return 0

    if args.force:
        final = new_content
    elif not existing.strip() and not init_path.exists():
        # init 文件完全不存在 + auto 模式 → 不创建（让用户走 from pkg.subpkg 风格）
        if args.init_mode == "auto":
            if not args.quiet:
                print("\n[AUTO-SKIP] No __init__.py + init_mode=auto -> no changes")
            return 0
        final = new_content
    elif not existing.strip():
        # init 文件存在但为空 → 创建（init_mode 任意）
        final = new_content
    else:
        # init 非空 → 合并
        final, _ = merge_existing_init(existing, new_content)

    # 决定行为
    if args.check:
        if final != existing:
            print("\n[FAIL] Out of sync. Run `python scripts/sync_init.py <pkg> --write` to fix.")
            return 1
        print("[OK] In sync.")
        return 0

    if args.diff:
        diff = make_diff(existing, final, str(init_path))
        if diff:
            print("\n" + diff)
        else:
            print("\n(no changes)")
        return 0

    if args.dry_run:
        if final != existing:
            print("\n--- would write ---")
            print(final)
        else:
            print("\n(no changes needed)")
        return 0

    # 写盘
    if final == existing:
        if not args.quiet:
            print("\n[OK] Already up to date.")
        return 0

    if not args.quiet:
        if existing.strip():
            print(f"\n[EDIT] Merging into existing {init_path}")
        else:
            print(f"\n[NEW] Creating {init_path}")

    init_path.write_text(final, encoding="utf-8")
    if not args.quiet:
        print("[OK] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
