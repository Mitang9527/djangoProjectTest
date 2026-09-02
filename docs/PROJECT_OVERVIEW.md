# 项目落地实践与能力全景

> 本文档梳理「如何把项目跑起来」与「项目已具备什么能力」，基于当前代码现状（2026-09-01）。
> 架构细节以 [ARCHITECTURE.md](ARCHITECTURE.md) 为单一事实源；能力逐项说明见 [FEATURES_GUIDE.md](FEATURES_GUIDE.md)。

## 一、项目定位

Django 5.x 企业级**多租户 SaaS 后端模板**：纯后端 API（零模板），前端 Vue3+Vite 分离；
同一仓库演进为**多服务架构**——主平台 + 独立 AI 生图服务（ai_studio）+ 通知服务（notice_service）。
三层解耦：`apps/`（业务，必装）、`framework/`（基础设施，可独立抽取为 pip 包）、`extensions/`（可选，整目录可删）。

| 服务 | 端口 | 职责 |
|------|------|------|
| 前端 Vue3+Vite | 5273 | 管理台；Vite 反代 `/api`、`/media` → 8300 |
| 主平台 Django | 8300 | HTTP+WebSocket 同端口（Daphne/ASGI）；全部业务 API |
| ai_studio | 8400 | 独立 AI 生图服务；WS `:8400/ws/ai-studio/<task_id>/?token=` 拉结果 |
| notice_service | - | 通知服务（站内信/渠道下发） |

> ⚠️ 端口约定：项目禁用 8000/5173。主平台与 ai_studio 的 `JWT_SIGNING_KEY` 必须一致。

## 二、落地实践

### 2.1 本地开发（最快路径，SQLite 即跑）

```bash
git clone <repo>
cd djangoProjectTest
python -m venv .venv                          # 本项目惯用 .venv（勿用系统 Python，缺 pydantic）
.venv/Scripts/pip install -r requirements.txt
cp .env.template .env                          # Windows: copy .env.template .env
# 改 .env：SECRET_KEY / DEBUG / ALLOW_DEMO_LOGIN=True（联调必需）/ JWT_SIGNING_KEY
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py init_permissions
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8300     # 仅 HTTP
# 完整模式（HTTP+WS）：daphne -b 0.0.0.0 -p 8300 djangoProjectTest.asgi:application
```

默认 `DB_ENGINE=sqlite3`，无需 PG/Redis 即可启动；读写分离副本 / Redis 缓存 / Celery 任务才需 PG+Redis。

### 2.2 Docker 部署

| 文件 | 用途 |
|------|------|
| `docker-compose.yml` | 开发环境：web / celery-worker / celery-beat / celery-flower / postgres / redis |
| `docker-compose.prod.yml` | 生产编排（`make prod-build / prod-up`） |
| `docker-compose.stack.yml` | 全栈部署：主平台 + ai_studio + notice_service 跨服务共享变量（`.env.stack` 注入 JWT_SIGNING_KEY 等） |

⚠️ 排障铁律：Docker 宿主残留 runserver/daphne/celery 会抢端口/MQ，先清理残留再 `force-recreate`。

### 2.3 配置体系（四层）

```
.env*  →  djangoProjectTest/model.py 的 global_config（Pydantic 校验）
       →  settings/base.py（16 分区）
       →  settings/{dev,prod,test}.py（manage.py 按 ENV 选模块）
```

- 三份 env 分工：`.env.template`（根目录 `.env` 的唯一来源模板）/ `.env.docker`（compose env_file）/ `.env.stack`（跨服务共享）。
- ⚠️ 新增/变更环境变量必须**同步 `.env` 与 `.env.template`**（校验：比对两文件键集合差集）。
- 生产硬校验：`JWT_SIGNING_KEY` 或 `API_SECRET_KEY` 为空且非 DEBUG → 启动 RuntimeError。
- 已知陷阱：pydantic-settings 复杂类型对 env 做 `json.loads`（逗号分隔配置用 `Any`+validator 手动 split）；
  env 空串时 `os.environ.get("KEY", default)` 的 default 不生效（写 `or default`）。

### 2.4 测试与质量

```bash
.venv/Scripts/python.exe -m pytest tests/ -q --no-cov   # 全套 451 通过（标准命令）
.venv/Scripts/python.exe manage.py check                # 启动自检（含 env 校验）
ruff check . / ruff format --check .                    # lint / 格式
```

- ⚠️ `manage.py test` 不带 `--settings` 会按 ENV 走 dev 配置 → 必须显式 `--settings=djangoProjectTest.settings.test` 或直接用 pytest（pyproject 已配）。
- ⚠️ pytest 收集阶段 import 测试模块即注册信号，测试库迁移播种数据时会产生预置审计记录，污染绝对计数断言——涉及审计计数断言须 setUp 清三张日志表。

### 2.5 运维与可观测

- **管理命令**：`init_permissions`（初始化权限）/ `cleanup_logs`（日志 TTL 归档清理，`--table/--days/--dry-run`）/ `check_menu_permissions`（菜单权限一致性校验，`--exit-code` 供 CI）/ `outbox_drain`（Outbox 事件投递）。
- **可观测**：Sentry（异常）、Prometheus + Grafana（指标，`deploy/`）、Request-ID（全链路追踪）、Loguru（结构化日志）、Flower（Celery 监控）、`/health/` 探针。
- **部署资产**：`deploy/` 含 nginx / k8s / postgres / prometheus / grafana 编排。

## 三、能力全景（九类）

| 能力域 | 已落地能力 |
|--------|-----------|
| **1. 多租户 SaaS 控制面** | Tenant/Plan/PlanFeature/订阅/Order/Invoice/FeatureFlag；租户级资源隔离与配额（含存储配额看板）；组织模型 Department/Post/data_scope |
| **2. 认证与账号安全** | 三重认证（SimpleJWT 双令牌 / API Key / Session）；OAuth2(Authorization Code+PKCE)；OIDC 角色映射；QR 扫码登录；MFA TOTP+恢复码；找回密码；会话管理（踢设备）；新设备提醒；自助改密；登录限流（IP+用户名双维度） |
| **3. 密钥与数据安全** | 敏感字段加密（SensitiveField 版本化 Fernet 多密钥轮换）；密钥管理（AES/HMAC/Nonce/轮换）；PII 脱敏（响应+日志） |
| **4. 授权体系** | RBAC 三层来源（超管→User.role→TenantMember.role）；动态菜单+按钮级权限（my-menus 下发）；菜单权限一致性校验；参考完整性守卫（引用冲突 409） |
| **5. 网关与流量治理** | API 签名中间件（公开端点白名单）；四维限流（IP/用户/租户/端点，Redis fail-closed 可配）；API 版本化（/api/v1）；统一五字段响应渲染；幂等（SETNX+Lua）；登录/注册/找回密码防刷 |
| **6. 可靠性工程** | 熔断/重试/舱壁/降级；分布式锁；事务 Outbox（三表+租约锁+退避+死信+幂等，`outbox_drain`）；读写分离（DB_REPLICA_URL 可选注入） |
| **7. 审计与合规** | 区块链式审计（SHA-512 哈希链 `verify_chain_integrity`）；审计 TTL 归档清理（AuditLogArchive 保留原始链）；登录/操作日志；AuditExcludeModel 白名单防写放大 |
| **8. 基础设施工具** | DB 连接池（psycopg3）；Redis 缓存+cachalot；i18n 五级语言链；文件上传白名单（SVG 禁入、视频 100MB 其余 10MB）+ 导出（CSV/Excel/PDF，>1 万条异步）；通知渠道（钉钉/飞书/邮件/企微）；文件资产管理（软删+恢复+配额） |
| **9. AI 与消息** | ai_studio 独立生图服务（OpenAI 兼容第三方 API，异步队列 `ai_studio.generate`，WS 结果推送）；apps/business/ai_gateway；RabbitMQ+Celery 任务栈；站内信+消息模板；告警引擎（规则/静默/抑制/升级） |

## 四、当前状态与遗留项

- **已闭环**：限流三套 / Outbox / MFA / 字典 / 告警 / FileAsset（管理+配额）/ 站内信 / OIDC / QR / 会话 / 改密 / 新设备提醒 / 找回密码 / OAuth2(PKCE) / 敏感值加密 / 参考完整性守卫 / 动态菜单+按钮级权限 / 菜单权限校验 / 审计 TTL 归档 / 配置中心分组管理。全套 **451 测试通过**。
- **已知遗留**：
  - `python-magic` 未安装，上传 MIME 检测降级为扩展名判断（安全性较低）；
  - `framework/mq`(pika) 与 Celery 并存，实际在用 Celery——死代码待清理决策；
  - 本地领先远端 12 个提交未 push（无 GitHub 凭据）；
  - 后置暂缓：滑块验证码、notice 对账。
- **维护纪律**（项目铁律，易踩坑）：
  1. 业务代码导入一律短路径 `system.*` / `business.*`，禁 `apps.*` 前缀（双 sys.path 致模型冲突）；
  2. `/api/*` 被签名中间件全局拦截，公开接口须加 `API_SIGNATURE_EXCLUDE_PATHS`；
  3. 自定义错误码用 `{"detail", "code"}` 结构（经渲染器 `errors.error_code` 透出）；
  4. 平台级管控写接口一律 `IsSuperAdmin`；
  5. NTFS 上 git commit 后分支 ref 可能不推进（游离提交）——提交后必验 `git rev-parse HEAD`，异常按 reflog→Python 改 packed-refs 预案修复。
