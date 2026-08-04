# 项目功能全景与使用指南

> 本文档面向**使用方 / 接入方 / 新同学**，回答三个问题：项目里**已有什么能力**、**怎么用**、**适合用在什么场景**。
> 架构与目录结构请见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)；本文档是它的"能力清单 + 用法手册"补充。
>
> 约定：所有 `import` 路径均为源码实测；代码块可直接抄用。

---

## 1. 项目概览

技术栈：Django 5.x + DRF + SimpleJWT + Channels(WebSocket) + Celery + Redis + drf-spectacular，数据库可接 PostgreSQL / MySQL / SQLite。

分层（详见 ARCHITECTURE.md）：

| 层 | 位置 | 性质 | 是否必装 |
|----|------|------|----------|
| 业务层 | `apps/` | 用户/多租户/告警/基础设施等业务应用 | 必装 |
| 可选层 | `extensions/` | ADB 设备管理 / APK 定制 / Web·移动自动化 | 可整目录删除 |
| 基础设施层 | `framework/` | 企业级工具集（容错/接口/数据/平台） | 必装 |

**路由挂载规则**：除 `users/core/saas/apk_tool` 为手动接线外，其余 app 自动挂在 `api/<app_name>/` 下。`extensions/web_automation` 不是 Django app，只能 `import` 使用。

**统一认证（三选一，已注册在 `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`）**：
- `JWTAuthentication`（对外接口主力）
- `framework.drf.api_key_auth.APIKeyAuthentication`（外部系统对接，`X-API-Key` 或 `Authorization: Bearer`）
- `SessionAuthentication`（浏览器页面）

---

## 2. 业务应用层（`apps/`）

### 2.1 users —— 用户与统一认证

**功能**
- 自定义 `User(AbstractUser)` 模型：`nickname`、`mobile(唯一)`、`avatar`、`role → saas.Role`(系统角色)。
- 注册 / 登录 / 登出 / 改密 / 密码重置；JWT（access+refresh）签发与刷新、黑名单登出。
- 用户 CRUD 与数据权限（非超管仅看自己数据）。

**如何使用**

获取 JWT：
```bash
curl -X POST /api/users/api/jwt/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"***"}'
# 返回 {"refresh":"...","access":"..."}
# 后续请求头: Authorization: Bearer <access>
```
服务层（`apps/users/services.py`）可直接调用：`RegisterService.register(data)` / `LoginService.login(username,password)` / `LogoutService.logout(request,refresh_token)` / `ProfileService.update_profile(...)` / `UserManageService.get_queryset(request_user)`。

**主要 API 端点**

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/users/register/` | 注册 |
| POST | `/api/users/login/` | 登录（JWT + Session） |
| POST | `/api/users/logout/` | 登出 |
| GET/PUT/PATCH | `/api/users/info/` | 当前用户信息（本人或超管） |
| GET | `/api/users/api/list/` | 用户列表（分页/搜索/数据权限） |
| GET | `/api/users/system-roles/` | 系统角色列表 |
| POST | `/api/users/api/jwt/login/` | 签发 JWT |
| POST | `/api/users/api/jwt/refresh/` | 刷新 access |
| POST | `/api/users/api/jwt/logout/` | JWT 登出（refresh 黑名单） |
| GET | `/api/users/api/jwt/verify/` | 校验 token |
| CRUD | `/api/users/api/manage/` | 用户管理（超管/指定权限） |

**应用场景**：任何需要"谁在访问、以何种方式鉴权"的后台/前端业务；SaaS 租户成员、系统管理员账户体系。

---

### 2.2 saas —— 多租户 / SaaS 控制面

**功能**
- 多租户隔离：`Tenant` + `TenantMember(role)` + `TenantMiddleware`（从 Session 读 `current_tenant_id` 注入 `request.tenant`）。
- 套餐计费：`Plan` / `PlanFeature` / `TenantSubscription` / `Order`(ORD-) / `Invoice`(INV-)。
- RBAC：`Permission(<module>.<action>)` + `Role`(系统角色 `tenant=null` / 租户角色) + 三层权限来源（超管 → `User.role` → `TenantMember.role`）。
- 配置中心：`GlobalConfig`(类型化 `parsed_value`) + `TenantConfig` + `FeatureFlag`(灰度/百分比/指定用户)。
- API 网关限流：`APILimitRule`(IP/用户/租户/端点四维) + 统计与告警。
- 缓存/连接池运维面板、系统备份、日志解析、数据导出。

**如何使用**

服务层入口（`apps/saas/services.py`）：
```python
from apps.saas.services import (
    TenantService, PermissionService, ConfigCenterService,
    FeatureFlagService, GatewayService, CacheService,
)
TenantService.switch_tenant(user, tenant_id, request.session)   # 切换租户
PermissionService.get_user_permissions(user, tenant_id=None)    # 当前权限集合
ConfigCenterService.get_config("site_name", default="")         # 读配置
ConfigCenterService.set_config("site_name", "新名", user, category="general")  # 写配置(自动记历史)
FeatureFlagService.is_enabled("new_dashboard", user, tenant)    # 特性开关
GatewayService.create_rule({"url_pattern":"/api/.*","throttle_type":"user","rate":"100/h"})
CacheService.invalidate_by_tag("dashboard")                     # 按标签失效缓存
```

权限声明示例：
```python
from apps.saas.permissions import SystemManagePermission, ReadWriteTenantPermission
permission_classes = [IsAuthenticated, SystemManagePermission]          # 预定义子类
# 或复合读写: ReadWriteTenantPermission.for_module("billing.order")     # GET 需 .view，写需 .manage
```

**主要 API 端点**（前缀 `/saas/api/`）：套餐/租户/订阅/配置/权限/角色/成员/订单/发票/全局配置/特性开关的标准 CRUD，外加：
`/me/permissions/`、`/me/tenants/`、`/me/switch-tenant/`、`/system/dashboard/`、`/system/backup/`、`/export/`、`/gateway/rules/`、`/cache/*`、`/db-pool/*`、`/config-center/*`、`/feature-flags/check/`。

**应用场景**：平台运营方做租户开通/计费；租户管理员做成员与角色管理；运营配置/灰度发布/限流治理；多租户 SaaS 产品的控制面。

---

### 2.3 alert_system —— 告警引擎

**功能**
- 规则引擎：`AlertRule`(level / condition_type=log_level·keyword·custom / channels / 升级 / 静默期 / 抑制窗口 / 最大触发次数)。
- 生命周期：`AlertSilence`(静默) → 抑制窗口(重复不重发) → 升级(超时未处理提升 level 重发) → 确认/解决。
- 多渠道通知：邮件 / 钉钉 / 飞书（`NotificationDispatcher`，配置优先 DB `AlertNotificationConfig` 再回退 settings）。
- 数据脱敏：`DataMasker`(手机/邮箱/身份证/银行卡/IP) + 响应中间件 + 日志 Filter 自动脱敏。

**如何使用**

手动触发告警（最常用入口）：
```python
from apps.alert_system.services.alert_engine import AlertEngine
AlertEngine.trigger(
    title="数据库主从延迟告警",
    content="replica lag = 120s",
    level="error",
    channels=["dingtalk", "email"],
)
```
规则评估（日志/事件接入）：`AlertEngine.evaluate(log_level, message, context)`；定时任务调 `check_escalations()` 升级；`acknowledge/resolve` 流转状态。

通知配置与脱敏：
```python
from apps.alert_system.masking import mask_data
mask_data({"mobile": "13800001111", "email": "a@b.com"})   # 自动按类型脱敏
```
数据库配置渠道：`AlertNotificationConfig(channel="dingtalk", config={...}, is_default=True)`；或 settings 配 `DINGTALK_WEBHOOK`/`DINGTALK_SECRET`、`FEISHU_WEBHOOK`/`FEISHU_SECRET`、`EMAIL_SEND_*`。

**主要 API 端点**（前缀 `/api/alert_system/`）：`/rules/`、`/silences/`、`/histories/`(+`/acknowledge/`、`/resolve/`、`/trigger/`)、`/notification-configs/`(+`/test/`)、`/stats/`。

**应用场景**：运维监控（日志关键字/级别触发）、业务异常主动告警、多渠道通知（CI/部署/审批）、敏感数据对外响应与日志合规脱敏。

---

### 2.4 core —— 基础设施（审计 / WebSocket / 健康 / 中间件）

**功能**
- 审计日志 `AuditLog`：操作留痕 + **防篡改哈希链**(`data_hash`/`previous_hash`/`verify_chain_integrity()`)；信号自动记录所有模型增删改；`OperationLogMiddleware` 注入请求上下文。
- WebSocket：`ChatConsumer`(聊天室) / `NotificationConsumer`(按 `user_{id}` 群组推送) / `OnlineUsersConsumer`(在线人数，Redis 有序集合 + 心跳)。
- 健康检查：`/health/`(db/redis/rabbitmq/disk) / `/health/live/`(K8s liveness) / `/health/ready/`(K8s readiness，非 pass 返 503)。
- 文件上传：`/api/upload/file/`、`/api/upload/image/`(类型/大小校验、压缩、水印)。
- API 自描述：`/api/config/` 自动归类所有端点。

**如何使用**

自动审计（业务 app 接入范式，参考 `apps/soul`）：
```python
from framework.helpers.audit_mixin import AuditLogMixin
from rest_framework import viewsets
class OrderViewSet(AuditLogMixin, viewsets.ModelViewSet):
    ...   # 所有写操作自动写 AuditLog
```
手动敏感操作：`log_sensitive_action('DATA_EXPORT', user=request.user, target_model='X')` 或装饰器 `sensitive_operation('DATA_EXPORT')`。

WebSocket 推送（从视图/任务推通知）：
```python
from apps.core.consumers import NotificationConsumer
await NotificationConsumer.send_notification(user_id, {"title": "审批待办", "body": "..."})
```

**应用场景**：全平台操作合规审计、实时消息/通知下发、K8s 探针、文件安全上传、请求级日志与审计上下文。

---

### 2.5 soul —— 示例/模板应用

最小示范 app（`Soul` 模型仅 `name` 字段，`SoulViewSet` 继承 `AuditLogMixin`），用于演示"标准 ViewSet + 自定义 action + 审计 Mixin"写法，**可直接作为新业务 app 的模板**。挂在 `/api/soul/`。

---

## 3. 基础设施层（`framework/`）

无业务依赖的纯工具集，按需 `from framework.<域> import ...`。按域分组如下。

### 3.1 容错（resilience）

#### 幂等 `idempotency`
- **功能**：基于 SETNX + Lua 原子抢占与状态机，保证同一幂等键的并发请求只执行一次，其余返回首次结果；可对请求体做指纹防篡改。
- **用法**
  ```python
  from framework.idempotency import idempotent, IdempotencyKeyMixin
  from rest_framework.views import APIView
  @idempotent(key_fields=["user_id","order_id"], ttl=600)
  def create_order(user_id, order_id, payload): ...
  class PayView(IdempotencyKeyMixin, APIView):   # 从请求头 HTTP_IDEMPOTENCY_KEY 取键
      idempotency_methods = ["POST"]
  ```
- **场景**：支付/下单/退款等写操作防重复提交与重试副作用。

#### 分布式锁 `locks`
- **功能**：Redis 可重入锁（看门狗自动续期）+ RedLock（多节点强一致）；装饰器 `@locked` 支持 `{arg}` 占位符。
- **用法**
  ```python
  from framework.locks import RedisLock, locked, RedLock
  with RedisLock("seckill:item:123", ttl=10, auto_renewal=True):
      deduct_stock(123)
  @locked("user:{user_id}", ttl=5)
  def transfer(user_id, amount): ...
  ```
- **场景**：库存扣减、定时任务抢占、缓存击穿重建、跨 Redis 节点的强一致锁。

#### 容错原语 `reliability`（resilience4j 风格）
- **功能**：`@retry`(指数退避+抖动) / `@circuit_breaker`(熔断 CLOSED/OPEN/HALF_OPEN) / `@bulkhead`(并发隔离) / `@fallback`(降级)。可组合。
- **用法**
  ```python
  from framework.reliability import retry, circuit_breaker, bulkhead, fallback
  @retry(max_attempts=5, backoff="exponential", retry_on=(ConnectionError,))
  def call_third_party(): ...
  @circuit_breaker(name="payment", failure_threshold=5, recovery_time=30)
  def charge(card): ...
  @bulkhead(name="slow_io", max_concurrent=8, max_wait=1.0)
  def heavy_task(): ...
  @fallback(default={"status":"degraded"})
  def recommend(uid): ...
  ```
- **场景**：外部依赖瞬时抖动重试、依赖持续失败时快速失败避免雪崩、慢依赖并发隔离、失败返回降级结果。

### 3.2 接口（api）

#### DRF 增强 `drf`
- **功能**：统一响应 `CustomRenderer`( `{status,code,message,data,errors}` )、全局异常处理器、`APIKeyAuthentication`、序列化器增强（`DesensitizedCharField` 脱敏 / `RecursiveField` 树形 / `EncryptedField` / `BulkSerializerMixin`）、校验器（手机号/身份证/银行卡/密码强度/`RuleEngine` 规则引擎）、ORM 增强（软删除/乐观锁/多租户/`BaseModel`）、分页（`PageNumber`/`LimitOffset`/`Cursor`）、`PermissiveAutoSchema`（消除 drf-spectacular 告警）。
- **用法**
  ```python
  from framework.drf.serializers import DesensitizedCharField, RecursiveField
  from framework.drf.validators import RuleEngine, validate_chinese_mobile
  from framework.drf.renderer import CustomRenderer
  engine = RuleEngine([{"field":"age","op":"gte","value":18}]); engine.check({"age":20})  # True
  ```
- **场景**：统一 API 契约与错误结构；软删除/乐观锁/多租户零样板；合规脱敏；复杂业务校验。

#### API 网关限流 `gateway`
- **功能**：IP/用户/租户/端点四维 DRF 限流器（Redis 滑动窗口）+ `GatewayMiddleware`(注入 `X-RateLimit-*`、拦截 429)。与 saas 的 `APILimitRule` 规则联动。
- **用法**
  ```python
  REST_FRAMEWORK = {"DEFAULT_THROTTLE_CLASSES": [UserThrottle, EndpointThrottle]}
  MIDDLEWARE += ["framework.gateway.middleware.GatewayMiddleware"]
  ```
- **场景**：开放 API / 多租户按维度限流、防刷、客户端友好的限流响应头。

#### API 版本管理 `versioning`
- **功能**：多版本共存、canary 按权重/规则分流、自动注入 `X-API-Version-*` 与 `Sunset`/`Deprecation` 响应头。
- **用法**
  ```python
  from framework.versioning import register_version, VersionSpec, VersionStatus
  register_version(VersionSpec(name="2024-01", status=VersionStatus.active, is_default=True))
  register_version(VersionSpec(name="2025-canary", status=VersionStatus.canary, canary_weight=0.1))
  MIDDLEWARE += ["framework.versioning.middleware.VersioningMiddleware"]
  ```
- **场景**：灰度发布、多版本并行、废弃提醒、自动降级。

#### API 签名 `api_signature`
- **功能**：HMAC-SHA256 签名防篡改 + `nonce`+`timestamp`(默认 300s) 防重放；`APISignatureMiddleware` 对白名单路径透明校验。
- **用法**
  ```python
  from framework.api_signature import generate_signature, verify_signature, APISignatureMiddleware
  sig = generate_signature("sk","POST","/api/pay", params={"a":1}, body="{}", nonce="x", timestamp=123)
  verify_signature(sig,"sk","POST","/api/pay", params={"a":1}, body="{}", nonce="x", timestamp=123)
  ```
- **场景**：服务间 / 开放 API 防篡改与防重放，业务视图无需改动。

### 3.3 数据（data）

#### 数据库连接池 `db`
- **功能**：对 PostgreSQL/MySQL 透明 monkey-patch 连接池（SQLite 走长连接），`pre_ping` 健康检查，暴露命中率指标。
- **用法**
  ```python
  DATABASES = {"default": {..., "ENGINE":"django.db.backends.postgresql",
      "_pool": {"enabled":True,"min_size":5,"max_size":20,"pre_ping":True}}}
  INSTALLED_APPS += ["framework.db"]   # ready() 自动 patch
  ```
- **场景**：高并发复用连接、减少 TIME_WAIT、降低建连开销；业务代码零改动。

#### 缓存 `cache`
- **功能**：版本化键(`v3:` 前缀) + 标签化批量失效(`invalidate_by_tag`)、`SCAN` 替代 `KEYS`、`cached`/`drf_cache_view` 装饰器、命中率统计、`register_warmup` 启动预热。
- **用法**
  ```python
  from framework.cache import cached, invalidate_by_tag, CacheStats
  from framework.cache.view_cache import drf_cache_view, T_1_MINUTE, TAG_DASHBOARD
  @cached("user_profile", ttl=300, tags=["user"])
  def get_profile(uid): ...
  @drf_cache_view("dashboard", timeout=T_1_MINUTE, tags=[TAG_DASHBOARD])
  def dashboard(request): ...
  invalidate_by_tag(TAG_DASHBOARD)   # 数据变更后失效
  ```
- **场景**：统一缓存键管理、租户/用户维度视图缓存、高频只读数据预热、命中率监控。

#### 消息队列 `mq`
- **功能**：RabbitMQ 管理（声明/发布/消费/延迟队列），`async_task` 装饰器把函数调用转异步。
- **用法**
  ```python
  from framework.mq import get_rabbitmq, async_task
  @async_task(queue_name="email")
  def send_welcome_email(user_id): ...
  get_rabbitmq().publish_delayed("email", {"user_id":1}, delay=3600)  # 1h 后发
  ```
- **场景**：发邮件/生成报表异步解耦、削峰、延迟任务（定时提醒）。

### 3.4 平台（platform）

#### 多语言 `i18n`
- **功能**：五级语言探测（请求头/query `?lang=`/Session/租户默认/默认）、`ORMTranslationBackend` 把文案存库动态管理、`localize_error`/翻译序列化错误。
- **用法**
  ```python
  from framework.i18n import t, register_translation, I18nMiddleware
  MIDDLEWARE += ["framework.i18n.middleware.I18nMiddleware"]
  register_translation("en","order.created","Order created")
  msg = t("order.created", default="订单已创建")   # 随请求语言返回
  ```
- **场景**：国际化后端、运行时改文案免发版、错误码按语言返回。

#### 密钥管理与轮换 `key_management`
- **功能**：多密钥签名器（轮换期新旧密钥同时可用）、`KeyRotationManager` 管理密钥生命周期、`rotate_secret_key` 平滑换 Django SECRET_KEY。
- **用法**
  ```python
  from framework.key_management import multi_key_sign, multi_key_unsign, rotate_secret_key
  tok = multi_key_sign("payload", salt="session")
  multi_key_unsign(tok, salt="session")          # 自动用当前有效密钥验签
  rotate_secret_key()                            # 旧 key 宽限期内仍可用
  ```
- **场景**：安全合规密钥轮换、避免轮换导致旧 token 集体失效。

#### 日志 `log_utils`（原 log_framework）
- **功能**：loguru 接管 Django/Celery/API/error 多源日志、JSON 输出便于 ELK、`RequestIDMiddleware` 注入 `X-Request-ID` 贯穿链路、`RateLimitFilter` 防日志风暴、`InterceptHandler` 桥接第三方 logging。
- **用法**
  ```python
  from framework.log_utils import LogManager, RequestIDMiddleware, get_request_id
  LogManager(log_dir="logs", level="INFO", json_output=True).setup()
  MIDDLEWARE += ["framework.log_utils.request_id.middleware.RequestIDMiddleware"]
  ```
- **场景**：统一日志管道、跨服务链路追踪、异常循环时防磁盘淹没。

#### 通知 `notice_utils`（原 notice_framework）
- **功能**：钉钉 / 飞书(Lark) / 邮件 / 企业微信 统一推送，内置 HMAC 签名与 `@` 能力。
- **用法**
  ```python
  from framework.notice_utils.dingtalk_control import DingTalkSendMsg
  from framework.notice_utils.wechat_send_control import WeChatSend
  from framework.notice_utils.sendmail_control import SendEmail
  DingTalkSendMsg().send_text("部署完成", mobiles=["138xxxx"])
  WeChatSend().send_markdown("## 告警\n**CPU 过高**")
  SendEmail.send_mail(["ops@example.com"], "日报", "内容...")
  ```
- **场景**：CI 报告、运维/业务告警、审批通知、文件消息（企业微信）。

#### 统一 HTTP 客户端 `http_client`
- **功能**：复用 `requests.Session` 连接池、自动重试(429/5xx 指数退避)、拦截器链(鉴权/日志/耗时)、懒加载 `default_client`。
- **用法**
  ```python
  from framework.http_client import HTTPClient, AuthInterceptor, LoggingInterceptor
  client = HTTPClient(base_url="https://api.x.com",
      interceptors=[AuthInterceptor(lambda: get_token()), LoggingInterceptor(slow_threshold_ms=1000)])
  resp = client.get("/users", params={"page":1})
  ```
- **场景**：对外 HTTP 调用统一治理，降低握手开销、统一鉴权与可观测。

#### 文件处理 `files`
- **功能**：上传校验（类型/大小/病毒扫描/随机文件名）、图片处理（压缩/水印/缩略图）、任意 Model 一键导出 CSV/Excel/PDF（中文支持）、临时文件清理与按天打包。
- **用法**
  ```python
  from framework.files.upload.validators import FileValidator, safe_file_upload
  from framework.files.export import ExportConfig, get_exporter
  v = FileValidator(allowed_types=["image/png"], max_file_size=5*1024*1024)
  safe_file_upload(request.FILES["f"], "media/", validator=v)
  cfg = ExportConfig(model_label="users.User", fields=["id","username"], headers=["ID","用户名"], filename="users")
  data = get_exporter(cfg, "xlsx").export(cfg.get_queryset())
  ```
- **场景**：安全上传、图片处理、后台数据导出报表、临时文件归档。

#### 运维工具 `ops`
- **功能**：`SSHClient`(远程命令/文件分发/隧道)、`TCPClient`(原始 TCP 对接)、`run_with_live_output`(实时子进程)、`FileMonitorManager`(watchdog 监控)、统一异常树。
- **用法**
  ```python
  from framework.ops.ssh_client import SSHClient
  with SSHClient("10.0.0.1","root", key_filename="/key.pem") as ssh:
      res = ssh.execute("df -h"); res.success and print(res.stdout)
  ```
- **场景**：自动化运维脚本、与硬件/遗留系统 TCP 对接、文件变更触发重新编译/同步。

#### 辅助 `helpers`
- **功能**：`@singleton` / `@measure_performance` / `@capture_exceptions` / `@rate_limit` / `AuditLogMixin`(自动审计) / 时间工具 / 系统信息(psutil)。
- **用法**
  ```python
  from framework.helpers.decorators import singleton, measure_performance
  from framework.helpers.audit_mixin import AuditLogMixin
  @singleton
  class Config: ...
  class OrderViewSet(AuditLogMixin, ModelViewSet): ...   # 自动留痕
  ```
- **场景**：横切关注点零样板化；审计 Mixin 满足合规。

#### 启动核心 `core`
- **功能**：`load_env_file`/环境判断、`StartupChecker`(依赖/App 就绪检查)、`init_sentry()`(错误监控 + 敏感字段脱敏)。
- **用法**
  ```python
  from framework.core.env_loader import is_production
  from framework.core.sentry_init import init_sentry
  is_production() and init_sentry()
  ```
- **场景**：启动期统一加载 `.env`、运行环境检查、集中接入错误监控。

#### 随机数据 `random_utils`
- **功能**：密码学安全随机——验证码/Token/UUID/强密码/测试数据批量生成（`secrets` 模块）。
- **用法**
  ```python
  from framework.random_utils.random_utils import RandomGenerator
  RandomGenerator.code(6)      # 短信验证码
  RandomGenerator.token(32)    # API Key / Session
  RandomGenerator.password(16) # 初始随机密码
  ```
- **场景**：生成验证码、安全 Token、强随机密码、测试数据构造。

---

## 4. 可选扩展层（`extensions/`）

不需要设备/自动化能力时，直接删除 `extensions/` 整目录即可，不影响 `apps/` 与 `framework/`。

### 4.1 adb_web —— ADB 设备 Web 化管理
- **功能**：基于 `adbutils` 把命令行 `adb` 封装为 Web 接口：设备列表/详情、第三方包、截屏、Shell(带补全)、应用启停/安装/卸载/导出、文本输入、环境配置写入、logcat、录屏、流量统计、Monkey 压测。
- **启用**：`AdbWebConfig` 自动注册；路由自动挂 `api/adb_web/`。
- **用法**
  ```python
  from adb_web.services import AdbService
  svc = AdbService()
  svc.list_devices(); svc.run_shell("192.168.1.1:5555","ls /sdcard"); svc.take_screenshot("192.168.1.1:5555")
  ```
  HTTP 端点：`GET api/adb_web/devices/`、`POST api/adb_web/devices/{serial}/screenshot/`、`POST .../shell/`、`POST .../app/install/`、`GET .../app/export/`、`POST .../monkey/` 等（URL 中 `serial` 的 `:` 需编码为 `%3A`）。
- **限制**：需真实 adb 设备 + 运行中 adb server；无 DB 模型/迁移；`input_text` 需预装 AdbKeyboard。
- **场景**：测试/运维远程管理 Android 真机或模拟器、自动化设备操作与压测。

### 4.2 apk_tool —— APK 定制 / 构建
- **功能**：Web 端对指定业务 APK 执行 反编译 → 配置注入 → 重打包 → zipalign → apksigner 签名，产出定制安装包（按机型/环境/登录方式/地图源等）。
- **启用**：`ApkToolConfig` 自动注册；路由由 `saas` 手动 include（`apk-tool/api/` + 页面 `apk-tool/`）。模型 `BuildTask` 已迁移。
- **用法**
  ```python
  from apk_tool.services.apk_service import decompile_apk, build_apk
  r = decompile_apk(str(task_id), 'large')
  if r['success']:
      build_apk(str(task_id), model_name='A310', launcher_module='large', recorder_enable=False)
  ```
  HTTP：`POST apk-tool/api/tasks/{id}/decompile|configure|build/`、`GET .../download/`、`GET terminal-list/` 等。
- **限制（重要）**：`ruamel.yaml` 未在 `requirements.txt` 声明（需补）；强 Windows 依赖（`zipalign.exe`/`apksigner.bat`）；需系统 JDK；仅支持白名单包名；签名密码硬编码于 `constants.py`（安全提示）；构建为**同步阻塞**，大包可能阻塞请求，建议异步化。
- **场景**：交付/运营为不同机型、环境、配置生成定制 APK。

### 4.3 web_automation —— Web / 移动端自动化（纯库）
- **功能**：对 Selenium(Web) 与 Appium(Android/iOS) 做轻量统一封装：链式调用、显式等待 `Waiter`、失败自动截图、`with` 自动 quit。
- **启用**：**非 Django app**，无路由；直接 `import`：
  ```python
  from extensions.web_automation.selenium import SeleniumClient, By
  with SeleniumClient(browser='chrome', headless=True) as web:
      web.get('https://example.com')
      web.wait().find(By.ID,'login').send_keys('user'); web.click(By.ID,'submit')
      web.screenshot('result')

  from extensions.web_automation.appium import AppiumClient, By
  with AppiumClient(platform='android', device_name='emulator-5554',
                    app_package='com.xxx', app_activity='.MainActivity') as app:
      app.wait().find(By.ID,'btn').click(); app.swipe('up')
  ```
- **限制**：无 Django 集成；依赖本地浏览器驱动或 Appium Server（`AppiumClient` 连接被拒报 `ServerNotRunningError`）。
- **场景**：自动化脚本、回归测试、Django 管理命令 / Celery 任务内调用——是可独立使用的自动化 SDK。

---

## 5. 通用约定与快速上手

**认证方式怎么选**
- 浏览器页面/后台 → Session；
- 对外 REST 接口 → JWT(`/api/users/api/jwt/login/`)；
- 服务间/开放对接 → API Key(`X-API-Key`) 或 API 签名(`api_signature`)；
- 更高安全级 → API 签名防篡改 + 防重放。

**如何新增一个业务 app（参考 `soul`）**
1. 在 `apps/` 下建包，写 `models.py` / `views.py` / `urls.py` / `serializers.py`；
2. 视图继承 `framework.helpers.audit_mixin.AuditLogMixin` 自动审计；
3. 返回统一用 `framework.drf.renderer.CustomRenderer` 结构；
4. 加入 `INSTALLED_APPS`（含 `apps.py` 会被自动发现），路由按需手动接线或在 `api/<app>/` 自动挂载。

**如何启用/禁用扩展**
- 删除 `extensions/` 整目录即可移除全部可选能力；
- 单独移除：`adb_web`/`apk_tool` 删对应目录（自动发现会跳过）；`web_automation` 删目录并停止 import。

---

## 6. 已知限制与待办

- **apk_tool**：`ruamel.yaml` 未在 `requirements.txt` 声明（导入会 `ImportError`）；强 Windows 二进制依赖；构建同步阻塞建议异步化；签名密码硬编码（需改为环境变量）。
- **adb_web**：无 DB 模型/迁移，产物落在 `MEDIA_ROOT/adb/`；强依赖真实设备与 adb server。
- **web_automation**：尚无在 views/Celery 中直接调用的示例，仅 `_smoke.py` 冒烟。
- **测试覆盖率**偏低（约 19%），建议优先补 `framework/` 核心模块（locks/idempotency/reliability/gateway）测试。
- 主路由存在预先存在的 `urls.W005`（namespace 'users' 不唯一）警告，属历史问题。

---

> 文档基于源码静态探查整理。功能/接口以各模块 `__init__.py` 与公开类/函数为权威；如发现与实际不符，以源码为准并同步更新本文档。
