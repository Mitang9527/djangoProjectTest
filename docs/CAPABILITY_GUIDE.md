# 能力使用指南（九类，2026-09-01）

> 按「怎么用」组织：先通用约定，再逐类给端点 / 代码范式 / 配置 / 场景。
> 端点前缀：业务 API 统一 `/api/v1/`；业务 app 由根 urls **自动发现挂载**（`/api/v1/{app_leaf}/`），
> 仅 users/core/saas/apk_tool 手动接线。响应统一五字段 `{status, code, message, data, errors}`。

## 0. 通用约定

- **认证**：`Authorization: Bearer <JWT>`（业务接口）或 API Key（服务间）。签名中间件对 `/api/*` 全局校验，
  公开端点须加入 `API_SIGNATURE_EXCLUDE_PATHS`（仅 `authentication_classes=[]` 无效）。
- **权限**：业务写接口走权限码（如 `file.view`/`file.manage`）；平台级管控写接口一律 `IsSuperAdmin`。
- **错误码**：自定义错误须返回 `{"detail": "...", "code": "..."}` 结构，经渲染器透出到 `errors.error_code`。
- **租户上下文**：`TenantMiddleware` 从 Session 读 `current_tenant_id` 注入 `request.tenant`。

---

## 1. 多租户 SaaS（apps/system/saas）

**端点**（`/api/v1/saas/`）：

| 能力 | 端点 |
|------|------|
| 套餐/功能点/订阅/订单/发票 | `plans/` `plan-features/` `tenant-subscriptions/` `orders/` `invoices/` |
| 租户/成员/切换 | `tenants/` `tenant-members/` `me/tenants/` `me/switch-tenant/` |
| 组织模型 | `departments/` `posts/` `roles/`（+ `Role.data_scope` 数据权限） |
| 配置中心 | `config-center/get|all|groups|public|set|delete|reload/`（读登录即可，写仅超管） |
| 特性开关 | `feature-flags/` `feature-flags/check/` `feature-flags/user/` `feature-flags/<id>/toggle/` |
| 权限/仪表盘 | `permissions/` `permissions/grouped/` `system/dashboard/` `system/logs/` |

**服务层**（`apps/system/saas/services.py`）：
```python
TenantService.switch_tenant(user, tenant_id, request.session)      # 切换租户（重签 JWT）
PermissionService.get_user_permissions(user, tenant_id=None)       # 当前权限码集合
ConfigCenterService.get_config("site_name", default="")            # 读配置（类型化解析）
ConfigCenterService.get_config_groups()                            # 分组看板（4 分类含空组）
FeatureFlagService.is_enabled("new_dashboard", user, tenant)       # 灰度判断
TenantProfileService.get_usage(tenant)                             # 配额用量（含文件存储）
```
**接入新租户能力**：模型挂 `tenant` FK → 注册进 `register_references` → 序列化器/ViewSet 按租户过滤 → 需要计费的在 `PlanFeature` 加配额项。

## 2. 认证与账号安全（apps/system/users）

**端点**（`/api/v1/users/`）：

| 能力 | 端点 |
|------|------|
| 注册/登录/登出/资料 | `register/` `login/` `logout/` `info/` |
| JWT | `jwt/login/` `jwt/refresh/` `jwt/logout/` `jwt/verify/`；`token/info/`（core） |
| MFA TOTP | `mfa/status/` `mfa/setup/` `mfa/confirm/` `mfa/disable/` `mfa/recovery/` |
| QR 扫码登录 | `qr-login/tickets/` `<ticket_id>/` `<ticket_id>/confirm/` |
| 找回密码（邮箱） | `password/reset/request/` `password/reset/confirm/` |
| 会话管理 | `sessions/`（列表 / 踢单设备 / 踢其余） |
| 修改密码 | `change-password/` |
| OAuth2(PKCE) | `oauth/<provider>/authorize/` `oauth/<provider>/callback/` `oauth/<provider>/bind/` |
| OIDC SSO（`OIDC_ENABLED` 时） | `oidc/login/` `oidc/callback/` `oidc/logout/` |
| API Key 生命周期 | `core/api-keys/`（签发/列表/改/吊销/rotate，管理员专属） |

**关键约定**：
- 登录签发链收敛到 `issue_login_tokens`；`RefreshToken.for_user()` 后自增 `token_version`（踢设备/改密/重置也自增，旧 token 即 401）。
- MFA 登录链：密码通过后同请求校验 `mfa_code`（TOTP 或恢复码），未带 → `mfa_required`，失败计入登录限流。
- 登录限流：`LoginThrottleService`（IP+用户名双维度，默认 5 次/300s、锁 900s，env `LOGIN_RATE_LIMIT_*` 可调，Redis 故障 fail-open）。
- 新设备登录自动站内信提醒。

## 3. 密钥与数据安全

**字段级透明加密**（`framework/security/sensitive.py`，已用于 `OAuthProvider.client_secret`）：
```python
from framework.security import SensitiveField
class OAuthProvider(models.Model):
    client_secret = SensitiveField(max_length=255)   # 落库 v1:<密文>，读回自动解密
```
- 手动加解密/脱敏：`encrypt_value` / `decrypt_value` / `mask_value`（多密钥轮换：加密走主密钥，解密依次尝试全部活跃密钥 + SECRET_KEY 兜底）。
- **约束**：密文字段不可 filter / order_by / 唯一约束；不可逆凭证（如 MFA 恢复码）用 HMAC 哈希。
- **密钥轮换**（`framework/key_management`）：`multi_key_sign` / `multi_key_unsign` / `rotate_secret_key`（新旧密钥宽限并行）。
- **PII 脱敏**：序列化用 `DesensitizedCharField`；日志/响应脱敏走 `pii.mask_generic`。

## 4. 授权体系

**RBAC 三层来源**：超级管理员 → `User.role`（系统角色）→ `TenantMember.role`（租户角色）；权限码 `Permission(<module>.<action>)`。
```python
from system.saas.permissions import SystemManagePermission, ReadWriteTenantPermission
permission_classes = [IsAuthenticated, ReadWriteTenantPermission.for_module("billing.order")]  # GET 需 .view，写需 .manage
# 平台级管控写接口：
permission_classes = [IsSuperAdmin]   # is_superuser 或 role.slug='super-admin'
```
**动态菜单/按钮级权限**（core）：
- 管理：`/api/v1/core/menus/`（仅超管 CRUD；按钮节点必绑 `permission` slug，否则 400）。
- 下发：`GET /api/v1/core/my-menus/` → `{"menus": [树], "permissions": [...]}`（按当前用户权限码过滤，父不可见子树整体丢弃；超管全量）。
- 一致性校验：`manage.py check_menu_permissions [--exit-code]`（防脏引用导致菜单对所有人不可见）。
**参考完整性守卫**（`framework/db/reference_guards.py`）：删除被引用对象返回可读 409 而非 500。
```python
register_references(Tenant, [(Role, ("tenant",)), (TenantMember, ("tenant",))])  # AppConfig.ready()
class PermissionViewSet(ReferenceGuardMixin, BaseModelViewSet): ...               # destroy 自动检查
raise_if_referenced(Role, role.pk)                                               # 或自定义 destroy 中调用
```

## 5. 网关与流量治理

| 能力 | 用法 |
|------|------|
| API 签名 | `APISignatureMiddleware` 全局；公开端点加 `API_SIGNATURE_EXCLUDE_PATHS`；`generate_signature/verify_signature`（HMAC-SHA256 + nonce + timestamp 300s） |
| 四维限流 | env `GATEWAY_THROTTLE_RATE_{IP\|USER\|TENANT\|ANON\|ENDPOINT}` 全局默认；saas `APILimitRule` 动态规则（ip/user/tenant/endpoint/anon）；优先级 APILimitRule > PlanFeature > TenantConfig > 全局；Redis 故障默认 fail-closed(429)，`GATEWAY_THROTTLE_REDIS_FAIL_OPEN=True` 降级放行 |
| 版本化 | `API_VERSIONS`（默认 `['v1']`）驱动；vN 优先 `{app}.{version}_urls`，缺失优雅跳过 |
| 幂等 | `@idempotent(key_fields=["user_id","order_id"], ttl=600)` 或 `IdempotencyKeyMixin`（请求头 `HTTP_IDEMPOTENCY_KEY`） |

## 6. 可靠性工程（framework/）

```python
# 容错四件套（可组合）
@retry(max_attempts=5, backoff="exponential", retry_on=(ConnectionError,))
@circuit_breaker(name="payment", failure_threshold=5, recovery_time=30)
@bulkhead(name="slow_io", max_concurrent=8, max_wait=1.0)
@fallback(default={"status": "degraded"})

# 分布式锁（可重入 + 看门狗续期；RedLock 多节点强一致）
with RedisLock("seckill:item:123", ttl=10, auto_renewal=True):
    deduct_stock(123)
@locked("user:{user_id}", ttl=5)
def transfer(user_id, amount): ...

# 事务 Outbox（业务成功则事件必不丢）
from framework.events import publish, register_handler
register_handler("order.created", on_order_created,
                 consumer_name="order.created.notify", consumer_module="apps.orders.events")
with transaction.atomic():
    order = Order.objects.create(...)
    publish("order.created", {"order_id": order.id}, trace_id=get_request_id())
# 投递：manage.py outbox_drain（或 Celery beat 周期调用）；失败指数退避+死信隔离+消费幂等
```
**读写分离**：仅设 `DB_REPLICA_URL`/DSN 才注入 replica（未设零风险回退）；写/事务 `using('default')`，`migrate` 只跑主库。

## 7. 审计与合规

- **自动留痕**：post_save 信号全模型增删改自动写 `AuditLog`；手工敏感操作用 `log_sensitive_action('DATA_EXPORT', user=...)` 或装饰器 `@sensitive_operation('DATA_EXPORT')`；ViewSet 可混入 `AuditLogMixin`。
- **防篡改**：`AuditLog.verify_chain_integrity()` 校验 SHA-512 哈希链（`previous_hash/data_hash`），返回断裂列表。
- **降噪**：`AuditExcludeModel` 表排除基础设施表（Outbox 三表/日志表等），防写放大。
- **查询**：`/api/v1/core/audit-log/`、`/api/v1/core/logs/login/`、`/api/v1/core/logs/operation/`。
- **TTL 归档清理**：`manage.py cleanup_logs --table audit|login|operation --days N --dry-run`——审计先归档进 `AuditLogArchive`（保留原始哈希链）再删，并级联重建在线存活链（`verify_chain_integrity` 保持全绿）。env 默认 `AUDIT_LOG_TTL_DAYS=180`、登录/操作 90。

## 8. 基础设施工具

| 能力 | 用法 |
|------|------|
| DB 连接池 | settings `DATABASES.default._pool = {enabled, min_size, max_size, pre_ping}`；`framework.db` ready() 自动 patch；运维端点 `/api/v1/saas/db-pool/*` |
| Redis 缓存 | `@cached("user_profile", ttl=300, tags=["user"])`；视图缓存 `@drf_cache_view(...)`；失效 `invalidate_by_tag(TAG)`；启动预热 `register_warmup`；版本化键 `v3:` |
| i18n | `I18nMiddleware` + `t("order.created", default="订单已创建")` + `register_translation("en", ...)`；五级语言探测（请求头/query/Session/租户/默认） |
| 上传白名单 | `/api/v1/core/upload/{file,image,video,audio}/`；代码级 `FileValidator(allowed_types, max_file_size)`；SVG 禁入(XSS)、视频 100MB 其余 10MB |
| 导出 | `/api/v1/saas/export/`（CSV/Excel/PDF，>1 万条自动转 Celery 异步 + 通知下载链接）；代码级 `ExportConfig + get_exporter(cfg, "xlsx")` |
| 通知渠道 | `framework/notice_utils`：`DingTalkSendMsg().send_text(...)` / `WeChatSend().send_markdown(...)` / `SendEmail.send_mail(...)`；站内信 + WS `NotificationConsumer` |
| 文件资产管理 | `/api/v1/core/file-assets/`（tenant/category/deleted/keyword 筛选；DELETE 软删、`POST {id}/restore/` 恢复；读 `file.view`、删/恢复 `file.manage`）；配额看板 `GET file-assets/usage/?tenant=<id>` |
| 统一 HTTP 客户端 | `HTTPClient(base_url, interceptors=[AuthInterceptor(...), LoggingInterceptor(...)])`（连接池复用 + 自动重试 429/5xx） |

## 9. AI 与消息

**ai_studio 独立服务（:8400，不维护用户表，信任主平台 JWT）**：
- `POST /api/v1/generate/` 创建生成任务（额度**冻结-确认扣减**：成功扣、失败返还，流水不可变）；
- `GET /api/v1/quota/` 额度查询（首访自动发 `AI_STUDIO_SIGNUP_GIFT`，默认 50）；
- `GET /api/v1/tasks/` 任务列表；结果推送 `WS ws://:8400/ws/ai-studio/<task_id>/?token=<JWT>`；
- **接真实模型**：只替换 `services/ai_studio/ai_studio_app/services.py` 的 `run_mock_generation`（当前占位 SVG）为 OpenAI 兼容调用（SDXL/可灵/极睿等）；
- 同步/异步：`AI_STUDIO_SYNC=1` 请求内同步（默认）；`0` 走 Celery 异步返回 PENDING。
- ⚠️ 主平台与 ai_studio 的 `JWT_SIGNING_KEY` 必须一致；Windows 下 Celery 用 `-P solo`。

**消息**：实际在用 RabbitMQ + Celery（worker/beat/flower，compose 内建）；`framework/mq`(pika) 为并存死代码，待整合决策。

**告警引擎**（`/api/v1/alert_system/`，自动挂载）：
- `rules/`（规则 CRUD）、`silences/`（静默）、`histories/`（历史）、`stats/`（统计）；
- 引擎特性：规则匹配 / 静默 / 抑制 / 升级；通知走渠道配置（邮件/钉钉/飞书/企微，空列表仅记录不外发）；内容自动脱敏。

---

## 附：新业务模块接入 Checklist（最小闭环）

1. `apps/business/<mod>/` 建 models → makemigrations → migrate；
2. urls.py 用 DefaultRouter 注册 ViewSet，根 urls **自动发现**挂到 `/api/v1/<mod>/`（无需手动接线）；
3. 需要审计/软删/多租户 → 混入 `AuditLogMixin` / 用 `framework.drf` 的 `BaseModel`；
4. 被外部引用 → `register_references` 注册守卫；
5. 写接口挂权限码（`for_module("mod.action")`），平台级管控用 `IsSuperAdmin`；
6. 公开端点 → 加 `API_SIGNATURE_EXCLUDE_PATHS`；
7. 高频读 → `@drf_cache_view`；写后 `invalidate_by_tag`；
8. 跨服务事件 → `publish` + `register_handler` + `outbox_drain`；
9. 测试 → `tests/test_<mod>.py`（pytest，注意审计计数断言先清三张日志表）。
