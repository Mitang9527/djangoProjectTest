# 架构说明（单一事实源）

> 本文档是项目架构的**单一事实源**。其余 `docs/*.md` 为各专题参考，README 仅保留概览与快速开始。

## 1. 分层总览

```
配置层    djangoProjectTest/   项目配置（settings base/dev/prod/test、ASGI/WSGI、Celery）
   │
业务层    apps/                通用后端业务应用（必装）
   │
可选层    extensions/          移动设备 / 自动化类扩展（按需启用，可整目录删除）
   │
基础层    framework/           企业级基础设施层（原 utils/，可独立抽取为 pip 包）
```

设计原则：**业务与基础设施彻底解耦**。`framework/` 不依赖任何业务 app；`extensions/` 依赖 `framework/` 与部分 `apps/`，但 `apps/` 绝不反向依赖 `extensions/`。

## 2. 目录地图

### `apps/`（业务应用，必装）
| App | 职责 |
|-----|------|
| `users` | 自定义 User 模型、JWT/Session/API Key 三重认证、权限服务 |
| `core` | WebSocket 消费者、审计日志、健康检查、文档、中间件 |
| `saas` | 多租户 SaaS：Plan/Tenant/Role/Permission/Order/Invoice/FeatureFlag/限流 |
| `alert_system` | 告警引擎：规则匹配/静默/抑制/升级 + 邮件/钉钉/飞书通知 + 数据脱敏 |
| `soul` | 示例/占位应用 |

### `extensions/`（可选扩展）
| 模块 | 职责 | 说明 |
|------|------|------|
| `adb_web` | ADB 设备 Web 化管理（基于 adbutils） | 含 AppConfig，自动发现为 Django app |
| `apk_tool` | APK 定制工具 | 含 AppConfig，自动发现为 Django app；路由由 `saas` 通过 `include('apk_tool.urls')` 挂载 |
| `web_automation` | Web/移动端自动化（selenium + appium） | **非** Django app，纯工具库，供其他模块导入 |

> 不需要设备/自动化能力时，直接删除 `extensions/` 整目录即可，不影响 `apps/` 与 `framework/` 运行。

### `framework/`（基础设施层，原 `utils/`）
按职责归并为以下域（实际子包保持细粒度）：

| 域 | 子包 |
|----|------|
| 容错 `resilience` | `reliability`（熔断/重试/舱壁/降级）、`locks`（分布式锁）、`idempotency`（幂等） |
| 接口 `api` | `drf`、`gateway`（四维限流）、`versioning`、`api_signature` |
| 数据 `data` | `db`（连接池）、`cache`、`mq` |
| 平台 `platform` | `i18n`、`key_management`、`log_utils`（Request-ID）、`notice_utils`、`ops`、`helpers`、`core`、`files`、`random_utils` |

## 3. 导入路径与发现机制

- `apps/` 与 `extensions/` 均通过 `sys.path.insert(0, ...)` 加入 Python 路径，因此 app 以**裸名**导入（`users`、`adb_web` 等）。
- `settings/base.py` 的 `discover_local_apps()` 扫描 `apps/` 与 `extensions/`，自动将含 `apps.py` 的目录注册进 `INSTALLED_APPS`；`web_automation` 无 `apps.py`，不会被误注册。
- 主路由 `djangoProjectTest/urls.py` 的 `discover_app_urls()` 同样扫描两目录，按 `api/<app_name>/` 自动挂载；`users/core/saas/apk_tool` 为手动接线，不参与自动发现。
- `framework` 为项目根下的顶层包，`from framework.xxx import ...` 即可使用。

## 4. 依赖管理

`requirements.txt` 保留为完整依赖清单（兼容旧安装方式）。按环境拆分建议：

- `requirements/base.txt` —— 运行时依赖（所有环境）
- `requirements/dev.txt` —— base + 开发/质量工具
- `requirements/test.txt` —— base + 测试工具
- `requirements/prod.txt` —— 仅 base

CI 仍使用 `pip install -r requirements.txt` 再单独装测试工具，未受影响。

## 5. `framework/` 抽取为独立 pip 包（可选下一步）

`framework/` 已是无业务依赖的纯基础设施包，可进一步抽离到独立仓库并发布：

```bash
# 1) 将 framework/ 移到独立仓库（保留 framework/ 目录结构）
# 2) 在独立仓库根添加 pyproject.toml：
#    [build-system]
#    requires = ["setuptools>=61.0"]
#    build-backend = "setuptools.build_meta"
#    [project]
#    name = "workbuddy-framework"
#    version = "0.1.0"
#    [tool.setuptools]
#    packages = [{include = "framework"}]
# 3) 在本项目安装：pip install -e ../workbuddy-framework
# 4) 删除本仓库内的 framework/ 目录，相关 import 无需改动
```

抽离后多项目可共享同一套企业级基础设施，本仓库只保留业务与可选扩展。

## 6. 已知约束

- `adb_web` 当前迁移为空（模型与迁移不同步），生产部署前需 `makemigrations` 补齐。
- 测试覆盖率偏低（约 19%），建议优先补充 `framework/` 核心模块（locks/idempotency/reliability/gateway）的测试。
- 主路由存在预先存在的 `urls.W005`（namespace 'users' 不唯一）警告，属历史问题，非本次重构引入。
