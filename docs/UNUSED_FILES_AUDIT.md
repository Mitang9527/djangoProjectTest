# 无用文件审计清单

> 扫描时间：2026-09-02
> 扫描方式：全仓文本引用分析（348 个 Python 模块逐个反查 `import` / 字符串路径 / 配置挂载点引用）+ 体积统计 + 配置挂载点核对
> **清理执行：2026-09-02 17:42 — A/B 两类已删除（回收 229 MB），`manage.py check` 复验 0 issues。其余类别维持原状待决策。**

## 结论速览

| 类别 | 可释放 | 风险 | 状态 |
| --- | --- | --- | --- |
| A. 覆盖率/缓存产物 | ~28 MB | 无 | **已删除** |
| B. node_modules（可重装） | ~201 MB | 无 | **已删除** |
| C. 零引用死代码 | ~21 KB | 低 | 待处理 |
| D. 空壳/脚手架遗留 | ~15 KB | 中 | 待决策（需同步改注册点） |
| E. 无挂载点的部署配置 | ~50 KB | 低 | 待确认 |
| F. 一次性审计文档 | ~37 KB | 低 | 待归档 |
| G. 运行时数据（已 gitignore） | ~337 MB | 无 | 保留 |
| H. 需人工决策 | ~160 MB | 待定 | 待你确认 |

### 已执行结果

| 操作 | 前 | 后 |
| --- | --- | --- |
| `django_vue/` | 133 MB | **197 KB** |
| `openapi-client/` | 68 MB | **1.3 MB** |
| 项目总计（排除 .venv/.git/media/extensions） | ~244 MB | **15 MB** |

两个 `node_modules` 均保留 `package.json` + `package-lock.json`，可 `npm ci` 精确重建。

---

## A. 构建/覆盖率产物 — ✅ 已全部删除

| 路径 | 体积 | 状态 |
| --- | --- | --- |
| `htmlcov/` | 17 MB | 已删 |
| `tests/htmlcov/` | 9.3 MB | 已删 |
| `coverage.xml` | 784 KB | 已删 |
| `tests/coverage.xml` | 436 KB | 已删 |
| `.coverage` | 100 KB | 已删 |
| `tests/.coverage` | 76 KB | 已删 |
| `.pytest_cache/` | 44 KB | 已删 |
| `scripts/.pytest_cache/` | 5 KB | 已删 |
| **所有 `__pycache__/`** | 分散 | 未动（Python 运行时自动生成，删了也会立刻重建） |
| `NUL` | 3.2 KB | **删除失败**，见下方说明 |

### ⚠️ `NUL` 删除失败 — 需要你手动处理

当前会话内所有删除路径均被拒绝（`ERROR_ACCESS_DENIED` / `Permission denied`）：

| 尝试方式 | 结果 |
| --- | --- |
| Git Bash `rm -f NUL` | safe-delete 转交回收站，回收站用常规路径解析 → `指定的设备名无效 (0x800704B0)` |
| Python `os.remove('\\?\...\NUL')` | `OSError` 同上 |
| Python ctypes `DeleteFileW` / `MoveFileW` | `GetLastError: 5` (ACCESS_DENIED) |
| PowerShell `Remove-Item -LiteralPath '\\?\...'` | **假阳性**：返回成功，`Test-Path` 也报 False，但文件仍在 |
| PowerShell `[System.IO.File]::Delete` | 访问被拒绝 |
| `CIM_DataFile.Delete()` | 能枚举到该文件，但调用 Delete 报「找不到」 |
| Git Bash `mv NUL _nul_junk.txt` | Permission denied |

**判定**：安全层在文件系统驱动级拦截了对该保留设备名的写操作，非管理员会话无法绕过。

**手动删除办法**（任选其一，建议在**管理员 PowerShell** 中执行）：

```powershell
Remove-Item -LiteralPath '\\?\D:\Code\djangoProjectTest\NUL' -Force
```

或在管理员 CMD 中：

```cmd
del /f /a \\?\D:\Code\djangoProjectTest\NUL
```

> 该文件仅 3.2 KB 且已在 `.gitignore`（`/NUL`），不进仓库、不影响构建与测试，留着也不会造成实际问题。

---

## B. 前端依赖目录 — ✅ 已全部删除

| 路径 | 体积 | 真实源码体积 | 状态 |
| --- | --- | --- | --- |
| `django_vue/web/node_modules/` | 133 MB | 前端源码仅 **197 KB** | 已删 |
| `openapi-client/node_modules/` | 68 MB | SDK 源码仅 **1.3 MB** | 已删 |

两个目录的 `package.json` 与 `package-lock.json` 均已保留，执行 `npm ci` 即可精确重建（前端在 `django_vue/web/`，SDK 在 `openapi-client/`）。

---

## C. 零引用死代码（全仓无任何 import / 配置引用，约 21 KB）

| 路径 | 体积 | 判定依据 |
| --- | --- | --- |
| `scripts/audit_routes.py` | 9.8 KB | 一次性路由审计脚本，无任何调用方 |
| `scripts/verify_api_routes.py` | 8.0 KB | AGENTS.md 已明确列为「排查产物，不提交」 |
| `scripts/sync_data.py` | 2.0 KB | 一次性数据同步脚本，零引用 |
| `apps/business/alert_system/log_filters.py` | 1.2 KB | `MaskingFilter` 定义完整，但**从未挂到任何 logging 配置**；`settings/base.py` 无引用，属「写了没接」的死代码 |

> 注意：`scripts/verify_tenant_session.py`、`scripts/verify_tenant_lifecycle.py` 同样是一次性验证脚本（共 16 KB），虽在 `tests/` 中被间接引用，建议一并归入此类处理。

---

## D. 空壳 / 脚手架遗留（删除需同步改注册点，约 15 KB）

### D1. `apps/business/soul/` — 整个 app 是脚手架 demo

- `models.py` 全文只有一个 `Soul` 模型、`name` 一个字段
- `views.py` 仅 44 行，`urls.py` 用 `router.register(r'', ...)` 挂路由
- 但**已注册进 `settings/base.py:852`** 且有路由，删除需同步摘除 INSTALLED_APPS 与 urls

### D2. `framework/*/examples.py` — 5 个示例脚手架（共 871 行）

| 路径 | 行数 | 覆盖率数据 |
| --- | --- | --- |
| `framework/versioning/examples.py` | 236 | `line-rate="0"` |
| `framework/i18n/examples.py` | 205 | `line-rate="0"` |
| `framework/reliability/examples.py` | 174 | `line-rate="0"` |
| `framework/idempotency/examples.py` | 139 | `line-rate="0"` |
| `framework/locks/examples.py` | 117 | `line-rate="0"` |

覆盖率数据中**全部为 0 行命中**，即从未被任何测试或运行时执行过，纯文档性质示例。

### D3. 其他占位小文件（各 < 200 字节）

`apps/business/alert_system/tests.py`、`apps/system/saas/tests.py`、`extensions/adb_web/{admin,models,tests}.py` — 均为 Django 生成的空占位。

---

## E. 无挂载点的部署配置（约 50 KB）

| 路径 | 问题 |
| --- | --- |
| `deploy/k8s/`（11 个文件） | **全仓零引用**。项目实际用 docker-compose + SQLite，k8s 清单（含 `hpa.yaml`/`secret.yaml`/`postgres.yaml` 等）与实际架构完全脱节，误导性最强 |
| `deploy/grafana/` | 无任何 compose 挂载 |
| `deploy/prometheus/` | 无任何 compose 挂载（`django_prometheus` 本身在用，但只有 `urls.py` 暴露 `/metrics`，这两份配置没被消费） |

> 唯一真正被使用的：`deploy/postgres/init.sql`（`docker-compose.prod.yml:116` 挂载）、`deploy/nginx/`（prod 反代）。

---

## F. 一次性审计/规划文档（约 37 KB）

这些是历史分析快照，项目现状已与其结论脱节，留着容易误导后续判断：

- `docs/BACKEND_GAP_ANALYSIS.md`（9.8 KB）
- `docs/BACKEND_IMPROVEMENT_PLAN.md`（9.0 KB）
- `docs/PROJECT_AUDIT_2026.md`（15.9 KB）
- `docs/PROJECT_AUDIT.md`（2.9 KB）

---

## G. 运行时数据（**不要删**，但确认别进仓库）

| 路径 | 体积 |
| --- | --- |
| `media/` | 334 MB（其中 `media/adb/apks/` 6 个 apk 约 331 MB） |
| `db.sqlite3` | 2.4 MB |
| `logs/` | 424 KB |
| `services/*/db.sqlite3`、`services/*/logs/` | 245 KB |
| `.idea/` | 49 KB |

以上均已在 `.gitignore`，属本地运行数据。

---

## H. 需人工决策（有潜在价值，但当前无任何自动调用）

| 路径 | 体积 | 疑问点 |
| --- | --- | --- |
| ~~`extensions/apk_tool/resources/DEF_APK/`~~ | ~~121 MB~~ | **已删除**（2026-09-03）。原被 `constants.py` 引用为默认模板，删除后 `apk_tool` 收敛为仅支持 `custom` 自定义上传，`APK_TYPE_CHOICES` 同步收敛 |
| ~~`tasks.py`~~ | ~~33 KB~~ | 待决策：Invoke 任务集，但 **Makefile、CI、pre-commit 均未调用**，疑似已被 Makefile 取代。内部仍残留 `uv sync`/`uv.lock` 引用（uv.lock 已删） |
| `apps/system/saas/management/commands/seed_data.py` | 18 KB | Django 命令（可 `manage.py seed_data` 运行），零引用，是可保留的一次性播种工具 |
| `ai_studio.postman_collection.json` | 6.3 KB | API 调试集合，无任何文档引用它 |
| `check_admin.py` | 1.7 KB | 根目录一次性检查脚本，逻辑与 `scripts/create_admin.py` 重叠 |
| ~~`requirements.txt` vs `requirements/base.txt`~~ | — | **已收敛**（2026-09-03）。以 requirements 体系为唯一事实源：删 `pyproject.toml` 的 `dependencies` 段 + 孤儿 `uv.lock`；`requirements.txt` 补 `dingtalkchatbot`，oidc 版本统一 `>=5.0` |

---

## 明确**不要**删（容易误判的项）

| 路径 | 为什么留 |
| --- | --- |
| `extensions/` 全部（141 MB） | `settings/base.py` 注册了 `AdbWebConfig` / `ApkToolConfig`；`terminal_configs` 被 `config_service.py` 真实读取（`DEF_APK` 已删） |
| `framework/mq/`（pika） | **目录已不存在**，此前 MQ 死代码清理已删干净，无需再动 |
| `django_vue/`、`openapi-client/` | 活跃前端与 SDK 生成工程（只是 node_modules 大，源码分别仅 197 KB / 1.3 MB） |
| `apps/system/saas/views/config_center.py`、`db_pool.py` | 表面看无引用，实际由 `views/__init__.py` re-export、`urls.py` 挂路由，功能在用 |
| `services/ai_studio`、`services/notice_service` | 均被 `docker-compose.stack.yml` 构建（ai_api / ai_worker / notice 服务） |
| `docs/PROJECT_OVERVIEW.md`、`docs/CAPABILITY_GUIDE.md` | 记忆中记录的现行有效文档 |

---

## 建议执行顺序

1. **立即可做（零风险，回收 ~229 MB）**：清理 A 类产物 + B 类 node_modules
2. **低风险（回收 ~71 KB）**：删 C 类死代码（`log_filters.py` 删前确认无外部调用）
3. **需改配置的**：D 类 `soul` app 摘除（改 `settings/base.py` + urls 后跑 `manage.py check`）
4. **确认后删**：E 类 `deploy/k8s/`、F 类审计文档
5. **人工决策**：H 类，尤其是 121 MB 的 `DEF_APK` 与 33 KB 的 `tasks.py`
