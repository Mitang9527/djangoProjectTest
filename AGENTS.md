# Django Enterprise Platform — Agent 开发规范

本文件是仓库级开发规范，约束自动化编码模型（Agent）与人工协作者。进入任何子目录工作前，先读本文件；与 `.workbuddy/memory/MEMORY.md`（长期项目记忆）配套使用——规范定义"必须怎么做"，记忆记录"踩过哪些坑"。

- 规范版本：1.0
- 架构基线：Django 5.x + DRF + SimpleJWT 模块化单体；`apps/system`（users / core / saas）+ `apps/business`（ai_studio 等业务模块）+ `framework/`（通用工具集）；独立 AI 服务 `services/ai_studio`（:8400）
- 端口约定：前端 5273（Vue3+Vite）、后端 8300、AI 服务 8400；禁用 5173/8000

---

## 1. 开始工作前

1. 阅读本文件与目标目录最近的说明文档。
2. 阅读 `.workbuddy/memory/MEMORY.md` 与最近的 `YYYY-MM-DD.md` 日志（记录历史坑与决策）。
3. 执行 `git status --short`，识别并保留用户已有修改（本仓库有未提交工作区是常态）。
4. 用 `rg`/Grep 定位现有实现、调用方与迁移，**不要凭文件名或旧对话推断实现**。
5. 明确变更边界、迁移影响、env 影响与验证范围。

## 2. 唯一事实源

| 信息 | 唯一事实源 | 禁止做法 |
| --- | --- | --- |
| 环境变量 | 根目录 `.env.template`（唯一模板来源）；本地用 `.env` | 只在 `.env` 加变量不同步 template；补完不跑 `manage.py check` |
| 运行环境选择 | `manage.py` 按 `ENV` 选模块：PROD→`settings.prod` / DEV→`settings.dev` / TEST→`settings.test` | 绕过 env_loader 直接 import settings |
| API 版本 | `settings.API_VERSIONS`（默认 `['v1']`）驱动 URL 版本化 | 新增版本只改 urls 不改 API_VERSIONS |
| 签名豁免 | `settings.API_SIGNATURE_EXCLUDE_PATHS` | 公开接口只改 `authentication_classes=[]` 不豁免签名 |
| 业务路由挂载 | `djangoProjectTest/urls.py` 统一 `/api/v1/` | 在新文件里散挂路由不经统一入口 |
| 权限 | `apps/system/saas/permissions.py` 的 slug 制 RBAC（`PermissionSlug`） | 视图内手写权限判断绕过权限类 |
| 限流 | `GATEWAY_THROTTLE_RATE_{IP\|USER\|TENANT\|ANON\|ENDPOINT}`（env 注入）+ `APILimitRule` 路由规则 | 硬编码限流值进业务代码 |
| 配置校验 | `djangoProjectTest/model.py` 的 `global_config`（Pydantic） | 跳过校验直接 `os.environ.get`（见铁律 4） |

## 3. 铁律（历史踩坑沉淀，违反即回归）

1. **签名语义**：`/api/*` 被签名中间件全局拦截。404=路径错，403=被签名拦（需加 `API_SIGNATURE_EXCLUDE_PATHS`）或权限不足。签名排除路径须是路由解析后的真实全路径，统一 `/api/v1/{users|core|saas}/*` 通配。
2. **导入路径**：业务代码一律短路径 `system.*` / `business.*`，**禁 `apps.system.*` / `apps.business.*`**（双 sys.path 致模型冲突 `Conflicting 'plan' models`）。
3. **pydantic-settings 类型陷阱**：字段声明为 `list[str]` 等 complex 类型时，pydantic-settings 会对环境变量先 `json.loads()`，逗号分隔字符串直接抛 JSONDecodeError **阻断启动**。逗号分隔配置一律用 `Any` + `field_validator(mode="before")` 手动 split（照抄 `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` / `SESSION_IDLE_TIMEOUT_EXEMPT_PATHS` 写法）。
4. **env 空值陷阱**：`.env` 里 `KEY=` 留空时环境变量存在但值为 `""`，`os.environ.get("KEY", default)` 的 default **不生效**。允许留空的变量一律写 `os.environ.get("KEY") or default`（历史坑：`LOG_LEVEL=` 空串导致 Django 抛 `Unable to configure logger 'django'`）。
5. **env 新增必验**：往 `.env`/`.env.template` 补变量后必须跑 `manage.py check` 复验启动（补齐本身可能引入回归）。
6. **User.role**：`User.role` 是 FK(`saas.Role`)；响应序列化只能取 `.name` / `.id`，禁塞模型实例进 JSON（TypeError）。
7. **上传白名单**：`framework/files/upload/validators.py` 强制扩展名白名单，MIME 同步；SVG 不入（XSS）；未知扩展名 `mimetypes.guess_type` 返回 `('', None)`，校验用 `if not guessed:`；视频 100MB 其余 10MB。
8. **Django 5.2**：`django.utils.timezone.utc` 已移除，用 `datetime.timezone.utc`。
9. **Loguru sink**：全部 sink 用可调用 format + 转义 `<` / `{}`（`_make_file_format` 内 `_escape_log_content`），禁含 `{message}` 字符串模板（消息体 `{'detail':...}` 或 `<module>` 会导致 sink 崩溃丢日志）。
10. **JWT token_version**：`User.token_version` + 全签发点（标准/DemoLogin/OIDC/LoginService/TokenService/主登录）在 `RefreshToken.for_user()` 后自增写 claim；改密也自增；`SlidingJWTAuthentication` 校验 claim≠version→401。
11. **Redis 故障**：基础设施客户端尊重 `enabled` + 快速失败（`_NullRedis` 降级）；限流 Redis 故障默认 fail-closed（`GATEWAY_THROTTLE_REDIS_FAIL_OPEN=False`），显式置 True 才降级放行。
12. **Windows 优先 `127.0.0.1`**（非 localhost）；SimpleJWT `exp` 用 `.timestamp()`。

## 4. 架构约束

- **模块化单体，不拆微服务**：业务能力进入 `apps/business/<module>`，中央业务模型不扩大。
- **跨模块依赖**：业务模块只依赖 `framework/` 与 `system.core` 的公开能力，禁直接 import 其他业务模块内部实现。
- **写放大意识**：1 次 DRF PATCH ≈ 业务 UPDATE + 二次 UPDATE + AuditLog×2 + 中间件 Log。避免无意义重复写库。
- **多租户**：租户上下文由 `TenantMiddleware` 注入 `request.tenant`；行级隔离用 `IsTenantMember*` 权限类与 `TenantQuerysetMixin`。新写 queryset 注意租户过滤。
- **读写分离**：副本仅在设 `DB_REPLICA_URL/DSN` 时注入；写/事务用 `using('default')`，migrate 只跑主库。

## 5. 验证要求（改动必做）

| 改动类型 | 必做验证 |
| --- | --- |
| 任何 Python 改动 | `python -m py_compile <文件>` |
| settings / env / model.py | `.venv/Scripts/python.exe manage.py check`（0 issues） |
| 新增/变更环境变量 | 比对 `.env` 与 `.env.template` 键集合差集（必须为 0）+ 反向 grep 确认 settings 有消费点 |
| 模型变更 | `makemigrations --check` 确认无遗漏迁移 |
| 接口行为 | 用 `.venv/Scripts/python.exe` 跑脚本或测试验证，临时数据用事务回滚不落库 |

- 验证统一用 `.venv/Scripts/python.exe`（系统 `D:\Python312` 缺 pydantic，勿用）。

## 6. 提交规范

- **显式暂存**：只 `git add` 本次改动的文件，禁 `git add -A`/`git add .`（仓库常有未跟踪排查产物：`NUL`、`_check_out.txt`、`_envcmp.txt`、`scripts/verify_*.py` 及 `*.report.txt`、`db.sqlite3.bak_*`，一律排除）。
- **post-commit 钩子坑（本仓库 NTFS 特有）**：`git commit` 会生成 commit 对象并打印成功，但**分支 ref 不推进**，新 commit 成为游离提交（`git branch --contains <sha>` 为空）。
  - 提交后必须验证：`git rev-parse HEAD` 应等于新 commit。
  - 若游离：用 Python 改写 `.git/packed-refs` 对应行（如 `92a02f3... refs/heads/Optimize/uploadfile`），**务必 `open(..., newline='')` 写入**，否则 `\n` 变 `\r\n` 导致 refname 末尾带 `\r`、git 报 `badRefName`。
  - 改完跑 `git fsck` 确认无 badRefName / invalid sha1。

## 7. OpenAPI 契约（前端 API 层不手写）

- 后端 schema：`python manage.py spectacular --file openapi-client/schema/openapi.json --format openapi-json`（Web 端 `/api/schema/` 仅 Admin 可看，自动化拉取走离线导出；实际执行用 `npm run export:schema`，内部自动调 `.venv` python）。
- 前端客户端生成：`openapi-client` 目录下 `npm run generate:api`（openapi-ts → TS 类型 + axios SDK），产物在 `openapi-client/src/generated/`；改完跑 `npm run typecheck` 校验。
- 禁止手写与后端接口重复的请求层；接口变更后重新生成，勿手工改 generated 文件。
- schema 的 `servers` 由 `SPECTACULAR_SETTINGS['SERVERS']` 提供（默认 `http://127.0.0.1:8300`），决定生成客户端的默认 baseUrl。
- **openapi-client 两个坑（勿改）**：
  1. `typescript` 必须锁定 6.x（`@hey-api/openapi-ts@0.99` 自身不声明该依赖；宿主装 typescript 7 原生版会崩 `Cannot read properties of undefined (reading 'AnyKeyword')`）。
  2. openapi-ts >= 0.99 会把两段式相对路径（`schema/openapi.json`）误判为 Hey API shorthand（`org/project`）报错；input 必须绝对路径（配置已用 `path.join(__dirname, ...)` 兜底）。
