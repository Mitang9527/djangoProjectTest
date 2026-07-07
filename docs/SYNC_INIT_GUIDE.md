# sync_init.py — 自动生成 / 同步 `__init__.py` 公开 API

> 一个零依赖的 Python 工具，**基于 AST 解析**自动维护包内 `__init__.py` 的 `from . import ...` 与 `__all__` 列表。

---

## 1. 它解决什么问题

每个 Python 包都有 `__init__.py`。手写它有三个痛点：

| 痛点 | 后果 |
|------|------|
| 新增子模块忘了 import | `from pkg import NewMod` 失败 |
| 改名 / 删模块忘了同步 `__all__` | `from pkg import *` 行为不一致 |
| IDE 自动写一堆 `__all__ = ["Foo", "_Bar", "_internal"]` | 公开 API 混入内部细节 |

`sync_init.py` **自动化这一切**，且**对业务代码零侵入**：
- **不 import 子模块**（避免拉起 Django / 数据库）
- **尊重 `__all__` 显式声明**（如 `idempotency` 模块）
- **跳过人工标记的文件**（`# sync-init: skip`）
- **智能合并现有 init**（保留 docstring / 注释 / 业务代码，只追加新符号）

---

## 2. 安装

零依赖！只用标准库 `ast` / `argparse` / `difflib` / `tempfile`。

把 `scripts/sync_init.py` 放到项目里即可。**没有第三方包要装**。

---

## 3. 用法

### 3.1 5 种模式

```bash
# ① --check：CI 模式（最常用），有差异时 exit 1
python scripts/sync_init.py mypackage --check

# ② --dry-run：显示会写什么，但不写盘
python scripts/sync_init.py mypackage --dry-run

# ③ --diff：显示 unified diff
python scripts/sync_init.py mypackage --diff

# ④ --write：真正写盘（默认行为）
python scripts/sync_init.py mypackage --write

# ⑤ --force：覆盖式重写（会丢失手工内容！慎用）
python scripts/sync_init.py mypackage --force
```

### 3.2 init 模式控制

```bash
# auto: 已有 init 则合并；没 init 则不创建（推荐；保护 from pkg.subpkg 风格）
python scripts/sync_init.py utils --check

# create: 即便没 init 也强制创建（让 from pkg import xxx 暴露所有子模块）
python scripts/sync_init.py utils --check --init-mode create

# skip: 不动 init，只扫描
python scripts/sync_init.py utils --check --init-mode skip
```

### 3.3 忽略目录

```bash
python scripts/sync_init.py mypackage --ignore "tests" --ignore "migrations"
```

默认忽略：`__pycache__`、`.git`、`.idea`、`.vscode`、`node_modules`、`.workbuddy`。

### 3.4 导出风格

```bash
# import 风格：from . import auth, billing
python scripts/sync_init.py mypackage --style import

# name 风格：from .auth import *；__all__ = ["auth_login", "auth_logout", ...]
python scripts/sync_init.py mypackage --style name
```

---

## 4. 跳过扫描：3 种方式

### 4.1 文件首行 `# sync-init: skip`

```python
# sync-init: skip
"""
本模块为内部实现，不应作为公开 API 暴露
"""
class _InternalHelper: ...
```

### 4.2 显式 `__all__` 优先

```python
__all__ = ["login", "logout"]  # 工具只看这 2 个，不会推断更多

def login(): ...
def logout(): ...
def _internal_helper(): ...   # 不会被加入 __all__
```

### 4.3 现有 init 首行 skip 标记

```python
# sync-init: skip
"""
这是手工管理的 init，永远不会被 sync_init 触碰
"""
from . import legacy_module
```

---

## 5. 合并行为（重点！）

**默认模式 (`--write`)** 智能合并：

| 现有 init 内容 | 行为 |
|----------------|------|
| 空文件 | 写入完整 auto-generated 内容 |
| 非空 + 有 docstring | 保留原 docstring / 注释 / 业务代码，**追加**新 `from . import` 与 `__all__` 项 |
| 首行 `# sync-init: skip` | **完全不动** |
| 有语法错误 | 备份后整体替换（写入新内容） |

合并策略是**"行级 patch"**：
- 找出现有 `from . import ...` 块，在其后**追加新行**
- 找到现有 `__all__ = [...]`，在最后一项后**追加新元素**
- 现有 docstring / 注释 / 业务代码**完全不动**

### 5.1 实际 diff 示例

**现有 `utils/cache/__init__.py`**（手工写）：
```python
"""
缓存工具包
"""
from .redis_client import get_redis
from .cache_manager import cache_get, cache_set

__all__ = [
    'get_redis', 'cache_get', 'cache_set',
]

# 自动注册缓存预热任务
from . import warmup_tasks
```

**新增了 `utils/cache/view_cache.py`**（含 `view_cache` 装饰器）

**运行**：`python scripts/sync_init.py utils/cache --write`

**结果**：
```python
"""
缓存工具包
"""
from .redis_client import get_redis
from .cache_manager import cache_get, cache_set

__all__ = [
    'get_redis', 'cache_get', 'cache_set',
    "view_cache",   # ← 新增
]

# 自动注册缓存预热任务
from . import warmup_tasks
from . import view_cache  # ← 新增
```

✅ docstring / 注释 / 业务代码完全保留；✅ 原 `__all__` 格式（单引号）保留；✅ 新项追加。

---

## 6. 集成到 CI

`.github/workflows/lint.yml`：

```yaml
- name: Check __init__.py is in sync
  run: |
    python scripts/sync_init.py apps --check
    python scripts/sync_init.py utils --check --init-mode create
```

`pre-commit` hook（`.pre-commit-config.yaml`）：

```yaml
repos:
  - repo: local
    hooks:
      - id: sync-init
        name: sync-init
        entry: python scripts/sync_init.py
        language: system
        args: ['--check']
        pass_filenames: false
```

---

## 7. 常见问题

### Q0: 报错 `AttributeError: module 'ast' has no attribute 'TypeAlias'`

原因：Python < 3.12。`ast.TypeAlias` 是 3.12 才加入的节点类型。
脚本已用 `getattr(ast, "TypeAlias", None)` 兼容 3.10 / 3.11，**无需任何处理**。如果你想支持 3.12+ 的 `type X = ...` 语法块识别，请升级到 3.12+。

### Q1: 工具会破坏我手工写的 `__all__` 吗？

**不会**。`__all__` 的原始引号风格 / 注释 / 分组全部保留，**只在末尾追加**新符号。

### Q2: 文件里有用 `# noqa: F401` 的 import 怎么办？

`from . import warmup_tasks  # noqa: E402, F401` 这种**整行**被识别为 `from . import`，**整个块会被检测到**。合并时新增的 import 会以新行追加，不会破坏原行的 noqa 注释。

### Q3: `__init__.py` 里有 `from .x import *` 怎么办？

工具会检测到 `from .x import *` 中 `x` 是一个名字。如果 `x` 又有 `__all__`，**不会被展开**。这种情况建议在 init 文件首行加 `# sync-init: skip`。

### Q4: 某些子模块是测试 / 内部工具，不想暴露

在子模块文件首行加 `# sync-init: skip`，或把它放到子目录（如 `internal/`），并在扫描时用 `--ignore "internal"`。

### Q5: 工具能不能从子目录的 `__init__.py` 一路追到最外层？

**不能**。`sync_init` 一次只处理一个包目录。要给多个包加 init，就多次调用：

```bash
python scripts/sync_init.py utils --check
python scripts/sync_init.py apps --check
```

或者写个 wrapper：

```bash
for pkg in utils apps saas; do
  python scripts/sync_init.py $pkg --check || exit 1
done
```

---

## 8. 限制 / 已知缺陷

| 限制 | 说明 |
|------|------|
| 1. 不追踪 re-export | 不会去解析 `from .x import Y`，`Y` 不会出现在最外层 `__all__` |
| 2. 不解析 type alias 链 | `X: TypeAlias = List[int]` 会被记录名字 `X`，但不会追类型 |
| 3. 嵌套子包递归 | 一次只处理直接子模块，不递归子包下的子模块 |
| 4. 合并是行级非语义 | 若现有 init 用 `from utils.x import y`（绝对导入），追加的会是 `from . import y` |
| 5. Windows GBK 编码 | 工具已做 `PYTHONIOENCODING=utf-8` 兜底；脚本里不用 emoji |

---

## 9. 测试

```bash
python -m unittest scripts.test_sync_init -v
```

**24 个测试覆盖**：
- AST 解析（5 类）
- 扫描（3 类）
- 生成（4 类）
- 合并（4 类）
- CLI 端到端（7 类）
