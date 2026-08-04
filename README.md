# Django 企业级架构项目模板

一个可复用的企业级后端架构模板，内置多租户 SaaS 体系；ADB 设备管理、APK 工具、Web 自动化等能力位于可选的 `extensions/` 模块，不需要时可整目录移除。项目以 Django 5.x 为核心，整合 DRF、Channels、Celery、Redis、PostgreSQL，覆盖认证、网关、容错、审计、可观测性等企业级关注点，可作为中大型后端项目的起步脚手架。

## 技术栈

| 层级 | 选型 |
|------|------|
| 语言 | Python 3.10+ |
| Web 框架 | Django 5.x、Django REST Framework |
| 实时通信 | Django Channels、Redis Channel Layer、Daphne (ASGI) |
| 异步任务 | Celery、Celery Beat、Flower |
| 数据存储 | PostgreSQL (psycopg3)、Redis (django-redis)、cachalot |
| 缓存与队列 | Redis、RabbitMQ |
| 认证 | SimpleJWT、API Key、Session |
| 可观测性 | Sentry、Prometheus、Request-ID、Loguru |
| CI/CD | GitHub Actions (lint -> type -> test -> security -> build) |
| 代码质量 | ruff、mypy、bandit、pre-commit |
| 测试 | pytest、pytest-django、pytest-cov、factory-boy |

## 核心特性

### 多租户 SaaS 体系
完整的订阅式多租户模型，覆盖计费与功能控制闭环：
- Plan（套餐）/ Tenant（租户）/ Role（角色）/ Permission（权限）
- Order（订单）/ Invoice（发票）/ FeatureFlag（功能开关）
- 租户级资源隔离与配额管理

### 三重认证机制
- JWT (SimpleJWT)：Access/Refresh 双令牌，支持黑名单登出
- API Key：服务间调用与外部集成
- Session：Web 管理后台访问

### WebSocket 实时通信
基于 Django Channels + Redis Channel Layer，支持聊天室、通知推送、实时设备状态下发。ASGI 入口由 Daphne 驱动，与 HTTP 复用同一端口。

### API 网关与四维限流
统一的网关层，支持以下四个维度的限流策略组合：
- IP 维度
- User 维度
- Tenant 维度
- Endpoint 维度

### 分布式容错
面向分布式场景的可靠性工具集，位于 `framework/reliability/` 与 `framework/locks/`：
- 熔断器 (Circuit Breaker)
- 自动重试 (Retry)
- 舱壁隔离 (Bulkhead)
- 降级回退 (Fallback)
- 分布式锁 (Distributed Lock)
- 幂等性 (Idempotency)

### 区块链式审计日志
采用 SHA-512 哈希链构建防篡改审计日志，每条记录包含前一条记录的哈希，任何中途篡改都会在校验时被发现。适用于合规审计与安全追溯场景。

### 数据库连接池与缓存
- 连接池：psycopg3 (PostgreSQL) / mysql-connector，复用连接降低建连开销
- 缓存层：django-redis + cachalot，自动缓存 ORM 查询结果

### 密钥管理与轮换
`framework/key_management/` 提供完整的密钥生命周期管理：
- AES 对称加密
- HMAC 签名
- Nonce 防重放
- 密钥轮换机制，支持新旧密钥并行解密期

### 数据脱敏
- 响应脱敏：序列化阶段对敏感字段打码
- 日志脱敏：记录前自动过滤密码、令牌、身份证等敏感信息

### 国际化 (i18n)
五级语言检测链，按优先级回退：
1. 请求头 `Accept-Language`
2. 查询参数 `lang`
3. Cookie
4. 用户偏好
5. 默认语言

### 数据导出
支持 CSV / Excel / PDF 三种格式。超过 1 万条记录时自动切换为 Celery 异步导出，导出完成后通过通知通道下发下载链接。

### 可观测性
- Sentry：异常自动上报与聚合
- Prometheus：指标采集与暴露
- Request-ID：全链路请求追踪，贯穿日志与响应头
- Flower：Celery 任务监控面板

### CI/CD
GitHub Actions 流水线，按以下阶段顺序执行，任一阶段失败即中止：
1. lint (ruff)
2. type (mypy)
3. test (pytest)
4. security (bandit)
5. build (镜像构建)

### 测试
基于 pytest + factory-boy，当前维护 42 个测试用例，覆盖核心业务逻辑与工具模块。

### pre-commit 钩子
提交前自动执行 ruff、mypy、bandit 三项检查，保证入库代码质量。

## 项目结构

项目自顶向下分为三层：**业务应用 `apps/`**、**可选扩展 `extensions/`**、**基础设施层 `framework/`**（原 `utils/`）。`extensions/` 为可选模块，不需要时可整目录删除，不影响核心后端运行。

```
djangoProjectTest/
├── apps/                          # 业务应用
│   ├── users/                     # 用户、认证、权限
│   ├── core/                      # WebSocket 消费者、基础视图
│   ├── saas/                      # 多租户 SaaS (Plan/Tenant/Order/Invoice/FeatureFlag)
│   ├── soul/                      # 示例应用
│   └── alert_system/              # 告警系统（规则/静默/抑制/升级 + 通知 + 脱敏）
├── extensions/                    # 可选扩展模块（按需启用，整目录可删）
│   ├── adb_web/                   # ADB 设备管理（Web 化管理，基于 adbutils）
│   ├── apk_tool/                  # APK 定制工具
│   └── web_automation/            # Web/移动端自动化（selenium + appium）
├── framework/                     # 基础设施层（原 utils，20+ 模块，可独立抽取为 pip 包）
│   ├── core/                      # 系统引导 (env_loader/startup/sentry/infrastructure)
│   ├── log_utils/                 # 日志 + Request-ID 追踪
│   ├── drf/                       # DRF 套件 (serializers/validators/renderer/pagination/api_key_auth)
│   ├── cache/                     # Redis 缓存
│   ├── db/                        # DB 连接池
│   ├── locks/                     # 分布式锁
│   ├── idempotency/               # 幂等性
│   ├── reliability/               # 熔断/重试/舱壁/降级
│   ├── http_client/               # HTTP 客户端封装
│   ├── gateway/                   # API 网关与限流
│   ├── i18n/                      # 国际化
│   ├── versioning/                # API 版本管理
│   ├── key_management/            # 密钥管理与轮换
│   ├── mq/                        # 消息队列
│   ├── notice_utils/              # 通知 (钉钉/飞书/邮件/企微)
│   ├── api_signature/             # API 签名
│   ├── ops/                       # 运维工具 (SSH/TCP/subprocess/watchdog)
│   ├── files/                     # 文件处理 (upload/export/zip/clean)
│   ├── random_utils/              # 随机工具
│   └── helpers/                   # 杂项工具 (time/system_config/decorators/audit_mixin)
├── djangoProjectTest/             # 项目配置
│   ├── settings/                  # base/dev/prod 分环境配置
│   ├── asgi.py                    # ASGI 入口
│   ├── routing.py                 # WebSocket 路由
│   └── urls.py                    # 主路由
├── tests/                         # 测试目录
├── docs/                          # 文档目录（ARCHITECTURE.md 为架构单一事实源）
├── requirements/                  # 依赖拆分（base/dev/test/prod）
├── docker-compose.yml             # 开发环境编排
├── docker-compose.prod.yml        # 生产环境编排
├── requirements.txt               # 完整依赖清单（兼容旧安装方式）
├── .env.example                   # 环境变量模板
├── Makefile                       # 常用命令封装
└── manage.py                      # Django 管理脚本
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- PostgreSQL 13+
- Redis 6+

### 2. 克隆与安装

```bash
git clone <repo-url>
cd djangoProjectTest

# 创建虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# Windows: copy .env.example .env
```

编辑 `.env`，至少配置以下项：

```env
SECRET_KEY=your-secret-key
DEBUG=True
DB_ENGINE=django.db.backends.postgresql
DB_NAME=saas_db
DB_USER=saas_user
DB_PASSWORD=your-password
DB_HOST=localhost
DB_PORT=5432
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 4. 初始化数据库

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py init_permissions
```

### 5. 启动服务

开发模式（仅 HTTP）：

```bash
python manage.py runserver 0.0.0.0:8000
```

完整模式（HTTP + WebSocket，推荐）：

```bash
daphne -b 0.0.0.0 -p 8000 djangoProjectTest.asgi:application
```

访问 http://localhost:8000

## Docker 部署

### 开发环境

```bash
# 构建并启动
make build
make up-d

# 执行迁移与权限初始化
make migrate
make init-perms
```

### 生产环境

```bash
make prod-build
make prod-up
```

开发环境使用 `docker-compose.yml`，生产环境使用 `docker-compose.prod.yml`，二者服务编排与资源配置不同。

## Make 命令

项目通过 Makefile 封装常用命令，涵盖本地开发、Docker、测试、代码质量、Celery 等场景。查看完整列表：

```bash
make help
```

常用命令示例：

```bash
make install          # 安装依赖
make migrate-local    # 本地迁移
make runserver        # 启动开发服务器
make run-daphne       # 启动 ASGI 服务器 (WebSocket)
make test             # 运行测试
make test-cov         # 运行测试并生成覆盖率报告
make lint             # ruff 检查
make typecheck        # mypy 类型检查
make celery-worker    # 启动 Celery Worker
```

## API 文档

项目内置交互式 API 文档，提供完整的接口定义与在线调试能力：

- Swagger UI: http://localhost:8000/api/swagger/
- ReDoc: http://localhost:8000/api/redoc/

出于安全考虑，API 文档仅对管理员开放，需使用超级用户账号登录后访问。

## 测试

```bash
# 运行全部测试
pytest

# 通过 Make
make test

# 带覆盖率报告
make test-cov

# 最快模式（无覆盖率）
make test-fast
```

覆盖率报告生成于 `htmlcov/index.html`，可在浏览器中查看逐行覆盖情况。

## 代码质量

```bash
make lint            # ruff 检查
make lint-fix        # ruff 自动修复
make format          # ruff 格式化
make typecheck       # mypy 类型检查
make security        # bandit 安全扫描
make pre-commit-run  # 运行全部 pre-commit 钩子
```

## 详细文档

- [架构说明（单一事实源）](docs/ARCHITECTURE.md)
- [JWT 认证指南](docs/JWT_AUTH.md)
- [WebSocket 部署指南](docs/WEBSOCKET_SETUP.md)
- [项目审计报告](docs/PROJECT_AUDIT.md)

## 许可证

MIT License
