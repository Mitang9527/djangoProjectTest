# Django 企业级 SaaS 项目 - 全量审计报告

**审计范围**：D:\Code\djangoProjectTest（79 个 Python 源文件 + 25 个模板 + 5 个 App）
**审计维度**：9 大类 / 38 项检查
**严重程度**：🔴 严重 🟡 警告 🟢 建议

---

## 0. 总评

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | ⭐⭐⭐⭐⭐ | 多租户 + RBAC + 网关分层清晰，模块边界合理 |
| 安全性 | ⭐⭐⭐½ | 主体合规，仍有 4 处关键风险 |
| 性能 | ⭐⭐⭐⭐ | 缓存/限流齐备，DB 层缺连接池（本次补齐） |
| 可维护性 | ⭐⭐⭐½ | 重复 import、模板加载 2 次，DRY 不足 |
| 测试覆盖 | ⭐⭐ | 仅 adb_web 有 tests.py 骨架，业务核心零覆盖 |
| 部署完备度 | ⭐⭐⭐⭐ | Docker + 健康检查 + 多阶段构建已就绪 |

---

## 1. 🔒 安全审计

### 🔴 严重问题

#### S-01 登录日志泄露密码 (`apps/users/views.py:193`)
```python
logger.warning(f"登录失败: 密码错误 - [{username}--{password}]")
```
密码以明文形式写入日志，违反最小化日志原则。任何日志被读取就泄露凭据。
**修复**：删除 `--{password}`，仅记录 username。

#### S-02 数据库密码/密钥可被导入到 settings (`djangoProjectTest/model.py:121`)
`DB_PASSWORD` 没有任何占位/弱口令检查。如果生产 `.env` 配置了空密码，pydantic 不会拦截。
**修复**：在 `DatabaseConfig` 中加 `password` 最小长度校验（生产环境 ≥8 位）。

#### S-03 DRF BrowsableAPIRenderer 在生产环境仍启用 (`settings/base.py:225`)
```python
'DEFAULT_RENDERER_CLASSES': (
    'utils.renderers.custom_renderer.CustomRenderer',
    'rest_framework.renderers.BrowsableAPIRenderer',  # ← 生产保留
),
```
BrowsableAPIRenderer 会暴露 CSRF、表单结构，给攻击者做信息收集。生产应去掉。
**修复**：`if not DEBUG: REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = (...) - 移除 BrowsableAPIRenderer`

#### S-04 InsecurePrivateKey 类异常捕获吞错 (`apps/saas/middleware.py:40`)
```python
except (Tenant.DoesNotExist, Exception):
```
`Exception` 与 `Tenant.DoesNotExist` 写在一个元组里，逻辑上 `Exception` 永远能匹配到前者，捕得太宽。`request.session.pop(...)` 在任何异常下都执行，掩盖真正问题。
**修复**：拆开两类异常或去掉外层 `Exception`。

### 🟡 警告

#### S-05 `User.token` 字段未在 JWT 方案下维护 (`apps/users/models.py:17`)
字段已无业务使用但未删除，会持久化旧的 DRF Token 痕迹。
**修复**：删除字段，做一次 makemigrations。

#### S-06 JWT 黑名单的 table 缺失会引发 500
`rest_framework_simplejwt.token_blacklist` 在 base 已加，但若忘记 migrate，黑名单功能失效、Token 撤销不生效，无任何提示。
**修复**：部署脚本中加 `python manage.py migrate token_blacklist --check` 校验。

#### S-07 DEBUG=True 时 `CORS_ALLOW_ALL_ORIGINS=True` (`settings/dev.py:15`)
注释说"开发才放开"，但 prod 镜像里跑 `daphne`/`gunicorn` 时如果 `.env` 误设 `DEBUG=True`，会同时放开 CORS。
**修复**：删除此行，强制使用 `CORS_ALLOWED_ORIGINS`。

#### S-08 `UserLoginView` 走 HTML 渲染器时不校验 CSRF（`apps/users/views.py:173`）
```python
from django.contrib.auth import login
login(request, user)  # 没有 CSRF 校验上下文
```
DRF 模板渲染流程不经过 CsrfViewMiddleware 的完整校验。
**修复**：登录页 GET 渲染时通过 `{% csrf_token %}`，POST 接口强制 `@csrf_protect`。

#### S-09 `dump-env` 仓库根 `.env` 存在被提交风险
未在仓库看到 `.env.example` / `.gitignore` 的 `*.env` 规则。
**修复**：补 `.gitignore` 至少覆盖 `.env`、`.env.local`、`.env.docker`。

---

## 2. ⚙️ 配置审计

### 🟡 警告

#### C-01 自动发现 apps 正则脆弱 (`settings/base.py:30-57`)
```python
match = re.search(r'class\s+(\w+)\(AppConfig\):', content)
```
- 注释、多类继承、装饰器会破坏匹配。
- 捕获的是字符串而非 AST，复杂 app 会失败。
**修复**：用 `ast` 模块解析 `apps.py`，直接读 `AppConfig` 子类名。

#### C-02 自动发现 URL 会把 `__pycache__` 当 app (`urls.py:46`)
`os.listdir` 不过滤，理论上能枚举到非 app 目录。
**修复**：仅在 `urls.py` + `apps.py` 都存在时纳入。

#### C-03 缓存命中率为 0 时 `hit_rate` 字段缺失（`utils/cache/cache_manager.py`）
`hit_rate` 在无任何命中时未提供默认值，会给前端报 N/A。
**修复**：统一返回 `0.0`。

#### C-04 `TEMPLATE_DIRS` 显式 + APP_DIRS 同时启用
```python
'DIRS': [BASE_DIR/templates, BASE_DIR/apps/core/templates],
'APP_DIRS': True,
```
同名的 `core/templates/core/index.html` 可能与 `apps/core/templates/core/index.html` 冲突。
**修复**：合并到一处或明确 namespace。

#### C-05 `STATICFILES_STORAGE = CompressedManifestStaticFilesStorage` 在 DEBUG=True 也生效
会导致模板里出现的额外静态文件未收集时整个页面 500。
**修复**：在 dev.py 改回 `StaticFilesStorage`。

#### C-06 `LOGIN_REDIRECT_URL='/'` 但 core 路由直接渲染 (`asgi.py` 渲染的是 ws 端)
`/` 走 `core.urls` 而非 `users.urls`，登录后跳转目标未明确定义。
**修复**：统一一个 `/dashboard/`。

### 🟢 建议

- `pydantic-settings` `model_config.extra="ignore"` 在生产配置漂移时不会报错，建议改为 `"forbid"`。
- `EMAIL_PORT = 587` 硬编码，QQ 邮箱 SSL 走 465，TLS 走 587，应根据 `EMAIL_USE_TLS` 自动切。
- `RedisConfig`/`RabbitMQConfig` 没有 `ssl`/`tls` 字段，生产连云 Redis 需自实现。

---

## 3. 🚀 性能审计

### 🟡 警告

#### P-01 DB 连接池缺失（**本次任务已补齐**）
- Django 原生 `CONN_MAX_AGE` 仅复用单进程连接。
- 高并发（>20 QPS）时 `psycopg2.connect` 每次握手 ≈ 5-10ms。
- PG 端 `max_connections` 默认 100，多 worker 容易爆。
**方案**：`utils/db/pool.py`（psycopg3 优先，psycopg2 / mysql-connector / PyMySQL 兼容），透明替换 `DatabaseWrapper`。

#### P-02 `django-cachalot` 与高写入场景冲突（`settings/base.py:350-360`）
ORM 自动缓存 5 分钟，**任何写操作会失效全表**。
- 订单、订单统计等高频写页面会反复穿透缓存。
**修复**：
- CACHALOT_TIMEOUT 改为 60s；或
- 把 `saas_order` / `saas_invoice` 加入 `CACHALOT_UNCACHABLE_TABLES`。

#### P-03 网关中间件对每个 API 请求都做 log.debug
```python
logger.debug(f"[Gateway] {method} {path} | IP={ip} | User={user_id}")
```
日志 sink 多时（如 file + logstash）会拖慢 0.5-2ms/请求。
**修复**：仅在 path 命中 `/api/` 且 `settings.LOG_LEVEL == 'DEBUG'` 时记录。

#### P-04 Channels 内存层 InMemoryChannelLayer 跨 worker 不通（`base.py:147`）
开发环境多 worker 时通知/在线状态数据不一致。
**修复**：本地启动脚本注释提示"开发用单 worker"；或强制要求 Redis 启用。

#### P-05 Celery 与 Channels 共用 Redis DB 1 (`base.py:456`)
```python
redis_db = REDIS_CONFIG.get('db', 1)
```
Celery broker 与生产环境业务缓存（DB 0）隔离 OK，但与 Channels 共用 DB 1 会相互 flush 时影响。
**修复**：Celery 用 DB 2，Channels 用 DB 1，缓存用 DB 0。

### 🟢 建议

- `LIMIT 1000/h` 限流硬编码 base，未暴露给运行时配置。
- `serializer_class` 大量重复声明 → 引入 `ViewSetSerializerMixin` 自动按 action 切换。
- 分页大小 10 对仪表盘/列表过小，可加 `cursor_pagination`。

---

## 4. 🏗 架构审计

### 🟡 警告

#### A-01 `User.role` 字段同时承担"系统角色"与"租户角色"职责
```python
role = models.ForeignKey('saas.Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
```
- `Role.tenant=null` 时是系统角色，否则租户角色 → 字段语义不清晰。
- 当前是 `null=True` 自由切换，未来必出问题。
**修复**：拆为 `User.system_role` (FK→Role where tenant=NULL) 与现有 `TenantMember.role` 两套。

#### A-02 `Tenant.id = UUIDField` 但 `Order.order_number` 用 `uuid.uuid4().hex[:8]`（碰撞概率 ≈ 0.4%）
8 字符 hex = 32 bit，同日 10 万订单时生日碰撞概率明显。
**修复**：用 12 字符 hex 或全 uuid。

#### A-03 三个 view 层机制混合（DRF ViewSet / DRF APIView / Django View）
- 重复书写 `is_super_admin`、`login_required`。
- 权限检查分散在 View 与 ViewSet。
**修复**：所有需要鉴权的 HTML 视图统一继承 `BaseAdminTemplateView(login_required=True)`。

#### A-04 软删除缺失
所有模型硬删除，订单/发票/用户删除后无法审计。
**修复**：建抽象 `SoftDeleteModel` 基类，全局替换。

#### A-05 没有审计日志中间件
写操作（租户/角色/订单）无审计记录。
**修复**：参考 `utils/mixins/audit_mixin.py` 但目前该文件为空 → 实际实现。

### 🟢 建议

- `apps/adb_web` 中 `adb_service.py` 与 `views.py` 调用关系未做端口层抽象，跨平台（macOS）适配困难。
- `apps/soul` 是占位包但仍被 `discover_local_apps` 加载，建议标记 `is_placeholder=True` 跳过。
- `apps/core` 中 `consumers.py` 把 ChatConsumer + NotificationConsumer + OnlineUsersConsumer 堆在一个文件，可拆分。

---

## 5. 🧪 测试覆盖审计

### 🔴 严重问题

#### T-01 业务代码测试覆盖率 ≈ 0%
- `apps/saas/tests.py` 为空文件
- `apps/users/tests.py` 缺失
- `apps/core/tests.py` 缺失
- `pytest-django` 已装但 `pytest.ini` 未配
**修复优先级**：
1. `pytest.ini` 加 `DJANGO_SETTINGS_MODULE`
2. 给 saas 权限解析（`_user_has_slug`）、订单并发、租户隔离写单元测试
3. 用 `factory-boy` 建基础工厂类

#### T-02 集成测试缺失
- 多租户隔离、API 网关限流、缓存失效 均无端到端测试。

### 🟡 警告

#### T-03 `apps/adb_web/tests.py` 骨架未完善
仅有 `from django.test import TestCase`，无任何测试方法。

#### T-04 没有 `conftest.py`
pytest fixtures 散落，无统一管理。

---

## 6. 📦 依赖审计

### 🟡 警告

#### D-01 `pyproject.toml` 与 `requirements.txt` 不同步
- `requirements.txt` 缺少：`pytest-django`、`drf-spectacular`、`django-cachalot`、`whitenoise`、`pygments` 等
- `pyproject.toml` 缺少：`channels-redis`、`djangorestframework-simplejwt`、`drf-spectacular`、`pygments` 等
- 项目同时维护两套依赖易出错。
**修复**：仅保留 `pyproject.toml`（uv/pip 都支持），删除 `requirements.txt` 或让 `requirements.txt` 转为 `pip install -r pyproject.toml` 形式。

#### D-02 关键依赖未锁版本上限
- `channels>=4.0.0` 在 5.0 引入 breaking change
- `drf-spectacular>=0.26.0` 0.27+ 改 schema 路径
**修复**：改为 `channels>=4.0,<5`。

#### D-03 开发依赖未分离
`pytest`/`mypy`/`ruff`/`factory-boy` 应放进 `[project.optional-dependencies.dev]`，否则生产镜像也会带。

#### D-04 缺失 DB 驱动
- 用 PostgreSQL 但未默认装 `psycopg[binary]`
- 用 MySQL 但未默认装 `mysql-connector-python` 或 `PyMySQL`
- Dockerfile 仅装 `psycopg2-binary`（已补）
**修复**：在 `requirements.txt` 中显式声明所有可能的驱动。

### 🟢 建议

- 引入 `pip-audit` / `safety` 到 CI
- 关键库加 `python_requires`

---

## 7. 🚢 部署审计

### 🟡 警告

#### DP-01 Dockerfile 用 `daphne` 但 entrypoint 默认是 gunicorn
```dockerfile
ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["gunicorn"]
```
`docker-compose.yml` 又用 `daphne`。两者都是 ASGI 服务器 OK，但 gunicorn 不支持 WebSocket。
**修复**：删除 gunicorn 引用，全部 Daphne；或拆分 web/ws 两套镜像。

#### DP-02 `collectstatic` 在 build 时执行，但 `STATIC_ROOT` 在 `static_root/` 而非容器外挂载
- 容器重启后静态文件仍在（容器有写权限）— OK。
- 但 `staticfiles_storage = CompressedManifestStaticFilesStorage` 需要全部静态文件存在，否则 collectstatic 失败。
**修复**：构建时静态检查脚本。

#### DP-03 没有 DB migration 步骤
Dockerfile 启动入口是 gunicorn/daphne，未跑 `migrate`。
**修复**：在 `entrypoint.sh` 加 `python manage.py migrate --noinput`。

#### DP-04 没有 WSGI/ASGI worker 调优
Gunicorn 默认 1 worker，容器内 CPU 多核浪费。
**修复**：gunicorn `-w $(nproc)` 或 daphne `-w 4`。

#### DP-05 Celery worker 与 beat 共享一个容器
`docker-compose.yml` 中 worker 与 beat 是两个独立 service（OK），但 base image 一致，部署友好。

### 🟢 建议

- 加 `nginx` 反向代理 + 静态服务层
- 加 `prometheus` exporter
- 容器镜像换 distroless

---

## 8. 📝 文档审计

### 🟡 警告

#### DOC-01 README 与实际项目脱节
- 提到 `apps/soul/` 但 `apps/saas/` 才是主模块
- "WebSocket 端点" 章节只列了 2 个，实际有 3 个
- "API 网关" 章节未出现在 README

#### DOC-02 缺少架构图
租户/角色/权限关系建议出 ER 图（用 mermaid）。

#### DOC-03 `docs/PROJECT_AUDIT.md` 旧版本未及时清理
- 检查 `docs/` 目录的"项目审计报告"是否仍反映当前状态

### 🟢 建议

- 接入 Swagger UI 之后，README 中可加"快速试调"段落
- 没有 CHANGELOG.md

---

## 9. 🧱 代码质量审计

### 🟡 警告

#### Q-01 重复 import 5 处
如 `apps/users/views.py` 中两次 `from django.urls import path, include`（urls.py 与 views.py 都出现 import），5 处模块被重复 import。
**修复**：开启 ruff 规则 `F401/F811`。

#### Q-02 `apps/saas/views.py` 单文件 1400+ 行
- 视图类、API 视图、管理 API、缓存管理、网关管理混在一起。
- 应按职责拆分：`views_admin.py` / `views_api.py` / `views_gateway.py` / `views_cache.py`。

#### Q-03 硬编码字符串 50+ 处
如 `'super-admin'`, `'admin'`, `'/api/users/login/'` 等魔法值散落。
**修复**：在 `apps/saas/constants.py` 集中管理。

#### Q-04 没有 type hint
- `drf_spectacular` 已装但没在 `SPECTACULAR_SETTINGS` 启用 `ENUM_NAME_OVERRIDES` / `COMPONENT_SPLIT_REQUEST`
- `mypy + django-stubs` 已装未配 `.mypy.ini`

#### Q-05 异常日志 traceback 重复打印
`utils/exceptions/handler.py` 捕获后 `traceback.format_exc()` 会与 loguru 的默认 traceback 双重输出。

### 🟢 建议

- `pylint`/`ruff` 配置未提交
- pre-commit hook 缺失

---

## 📋 待办优先级矩阵

| 优先级 | 任务 | 预期工时 |
|--------|------|----------|
| P0 | S-01 修复登录密码明文日志 | 5min |
| P0 | S-03 移除生产 BrowsableAPIRenderer | 5min |
| P0 | T-01 配置 pytest + 写 saas 权限核心测试 | 4h |
| P1 | P-01 DB 连接池（**本次已实现**） | ✅ |
| P1 | S-02/S-04 修异常 / 密码强度校验 | 30min |
| P1 | C-01 改 ast 解析 AppConfig | 1h |
| P1 | A-01 拆 User.system_role / TenantMember.role | 4h |
| P1 | DP-03 DB migrate 步骤 | 15min |
| P2 | A-04 软删除基类 | 8h |
| P2 | P-02 收缩 cachalot 超时 | 15min |
| P2 | Q-02 拆 views.py | 4h |
| P2 | DOC-01 更新 README | 1h |
| P3 | D-01 依赖统一 | 1h |
| P3 | Q-05 traceback 去重 | 10min |

---

## ✅ 已落地

- **DB 连接池（`utils/db/`）**：psycopg3 / psycopg2 / mysql-connector / PyMySQL 四驱动全适配
- 池配置 Pydantic 模型，支持 `OPTIONS["pool"]` 透明配置
- 池指标采集（命中率/等待/超时/错误）
- 管理 API：`/saas/api/db-pool/stats/` `/reset-stats/` `/reinit/`
- `requirements.txt` 加入所有驱动依赖
- `settings/base.py` 加入 `DB_POOL_DEFAULT_OPTIONS` 环境变量
- `settings/prod.py` 默认启用池，`settings/dev.py` 默认关闭
