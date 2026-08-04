# 监控与可观测性接线手册

本文档说明本项目的监控能力现状，以及**如何让它们真正运转起来**。
配套架构与能力清单见 `docs/ARCHITECTURE.md` 与 `docs/FEATURES_GUIDE.md`。

---

## 1. 监控能力总览

| 维度 | 能力 | 状态 | 入口 / 配置 |
|---|---|---|---|
| 健康检查 | DB / Redis / RabbitMQ / 磁盘探活 + liveness/readiness | ✅ 已具备 | `apps/core/health.py`；端点 `/api/health/`、`/api/health/live/`、`/api/health/ready/` |
| 指标 | Prometheus 通用指标（HTTP/DB/缓存） | ✅ 已具备 | `django_prometheus`（已装 middleware + `/metrics`） |
| 指标 | 自定义业务指标（API 延迟/错误率/缓存命中/限流/告警量等） | 🆕 新增 | `framework/metrics/` + 中间件 |
| 错误监控 | Sentry 上报 | ⚠️ 需配置 | `settings/base.py` + `.env` 的 `SENTRY_DSN` |
| 队列监控 | Flower 面板 | ✅ 已具备 | `docker-compose.yml` `celery-flower:5555` |
| 链路追踪 | request_id 贯穿日志 | ✅ 已具备 | `framework/log_utils/request_id/` |
| 告警消费端 | alert_system 引擎（钉钉/飞书/邮件/企业微信） | ✅ 已具备 | `apps/alert_system/` |
| 日志监控 | ERROR 日志突增（loguru sink 计数 + 阈值） | 🆕 新增 | `framework/log_utils/error_spike.py` + `core.tasks.check_error_spike` |
| DB 监控 | 慢查询（全局计时）/ 长事务（pg_stat_activity） | 🆕 新增 | `framework/db/monitoring.py` + `core.tasks.check_long_transactions` |
| 安全扫描 | TLS 证书到期 / 密钥泄漏 / 密钥年龄 | 🆕 新增 | `framework/key_management/scan.py` + `key_management.security_audit` |
| 报表 | 每日系统健康日报（推钉钉/飞书） | 🆕 新增 | `core.tasks.daily_health_report` |

**本次补齐的两处断点：**
1. `/metrics` 此前没人采集 → 新增 `deploy/prometheus/` 抓取 + 告警规则 + Grafana 面板。
2. 依赖组件即便挂了也无人告警 → 新增主动探活 beat 任务 `core.tasks.probe_dependencies`，失败自动经 `alert_system` 发告警。

---

## 2. 自定义指标（`framework/metrics`）

所有指标带 `django_` 前缀，与 `django_prometheus` 通用指标区分。
`prometheus_client` 未安装时自动降级为 no-op，不影响业务。

| 指标 | 类型 | 含义 |
|---|---|---|
| `django_api_requests_total` | Counter | API 请求数（labels: method/endpoint/status） |
| `django_api_request_duration_seconds` | Histogram | API 延迟（method/endpoint） |
| `django_api_errors_total` | Counter | API 错误数（status≥400） |
| `django_cache_hits_total` / `django_cache_misses_total` | Counter | 缓存命中/未命中（backend） |
| `django_rate_limit_rejections_total` | Counter | 限流拒绝（scope） |
| `django_websocket_online_users` | Gauge | 当前 WebSocket 在线用户 |
| `django_celery_queue_backlog` | Gauge | Celery 队列积压（queue） |
| `django_alerts_triggered_total` | Counter | 告警触发数（level） |
| `django_error_logs_total` | Counter | ERROR+ 日志累计（source） |
| `django_error_logs_window` | Gauge | 当前窗口内 ERROR+ 日志数（beat 写入） |
| `django_db_slow_queries_total` | Counter | 慢查询累计（alias） |
| `django_db_query_duration_seconds` | Histogram | DB 查询耗时（alias） |
| `django_db_long_transactions` | Gauge | 长事务数量（alias，beat 写入） |

**已接线的埋点：**
- API 指标：中间件 `framework.metrics.middleware.MetricsMiddleware` 统计每个请求（已接入 `settings.MIDDLEWARE` 第 19 项，自动排除 `/metrics`、`/api/health`、静态/媒体/管理后台等路径）。
- 告警指标：`apps/alert_system/services/alert_engine.py` 的 `AlertEngine.trigger` 内 `inc(django_alerts_triggered_total)`。
- ERROR 日志：loguru sink `framework/log_utils/error_spike.py::_error_spike_sink` 在 `LogManager._setup()` 中注册，统计每条 ERROR+ 并 `inc(django_error_logs_total)`。
- DB 慢查询：`framework/db/monitoring.py` 在 `DBPoolConfig.ready()` 中 patch `CursorWrapper.execute/executemany` 全局计时，超阈值 `inc(django_db_slow_queries_total)` + 采样告警日志 + 节流告警。

**待接线（预留函数，按需调用）：**
`framework/metrics.metrics` 提供了 `record_cache_hit/miss`、`record_rate_limit_rejection`、`set_websocket_online_users`、`set_celery_queue_backlog`。在 `framework/cache`、`framework/gateway`、`core`（WebSocket）、`framework/mq` 的对应路径调用即可，无需改中间件。

---

## 3. 主动探活任务（让"健康检查"真正告警）

`apps/core/tasks.py::probe_dependencies`：
- 复用 `core.health.HealthChecker().run_all()` 检查 DB / Redis / RabbitMQ / 磁盘。
- 任一组件 `FAIL` 时，调用 `AlertEngine.trigger(level="error", channels=...)` 创建告警并按 `settings.ALERT_PROBE_CHANNELS` 外发。
- `ALERT_PROBE_CHANNELS` 默认为空列表（此时仅记录告警历史、不外发）；配置为通知系统支持的渠道（如 `["dingtalk","feishu","email"]`）后即自动外发。

该任务已通过 data migration 注册为**每 5 分钟**调度（见第 5 节）。

---

## 4. Prometheus + Grafana 部署

### 4.1 启动 Prometheus
```bash
prometheus --config.file=deploy/prometheus/prometheus.yml
```
- `scrape_configs.job_name=django` 抓取 `web:8000/metrics`（Docker 环境用服务名；裸机改为 `localhost:8000`）。
- 告警规则见 `deploy/prometheus/rules/django_alerts.yml`（高错误率 / P95 延迟 / 实例 down / DB 查询突增）。
- 如需把 Prometheus 告警转发到钉钉/飞书，额外配置 Alertmanager；或依赖第 3 节的 `probe_dependencies` 走项目内置 `alert_system`。

### 4.2 导入 Grafana 面板
1. Grafana → Dashboards → Import。
2. 上传/粘贴 `deploy/grafana/dashboards/django-overview.json`。
3. 选择 Prometheus 数据源（面板用 `${DS_PROMETHEUS}` 变量）。
面板含：API 请求率、错误率、P95 延迟、DB 查询速率、缓存命中率、告警触发、WebSocket 在线、Celery 积压、HTTP 响应分布。

---

## 5. 周期任务注册（填平"调度真空"）

此前项目已定义多个 `@shared_task` 但**没有任何 `PeriodicTask` 记录**，Beat 实际调度的周期任务为 0。
`apps/core/migrations/0004_register_beat_schedules.py` 一次性注册：

| 任务名 | task | 周期 |
|---|---|---|
| probe-dependencies | `core.tasks.probe_dependencies` | 每 5 分钟 |
| alert-escalation-check | `alert_system.check_escalations` | 每 5 分钟 |
| auto-backup-database | `core.tasks.auto_backup_database` | 每日 03:00 |
| cleanup-old-backups | `core.tasks.cleanup_old_backups` | 每周日 04:00 |
| auto-rotate-secret-key | `key_management.auto_rotate_secret_key` | 每日 02:00 |
| clean-temp-files | `files.clean_temp_files` | 每小时 |
| clean-old-uploads | `files.clean_old_uploads` | 每日 05:00 |
| check-error-spike | `core.tasks.check_error_spike` | 每 5 分钟 |
| check-long-transactions | `core.tasks.check_long_transactions` | 每 5 分钟 |
| security-audit | `key_management.security_audit` | 每日 03:10 |
| daily-health-report | `core.tasks.daily_health_report` | 每日 09:00 |

**生效方式：** 正常迁移即可（`python manage.py migrate`）。`django_celery_beat` 使用 `DatabaseScheduler`，这些记录写入数据库后 Beat 自动按周期触发。
> 注意：本机 `django.setup()` 在此环境下启动极慢，**未在此环境实跑迁移**，请在可正常启动 Django 的环境（CI / 部署）执行 `migrate` 验证。

---

## 6. Sentry 错误监控

生产环境填入 DSN 即自动启用（`settings/base.py`：`if SENTRY_DSN and not DEBUG: init_sentry()`）。
编辑 `.env`（参考 `.env.template`）：
```
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
```

---

## 7. P2 监控增强（已实现）

### 7.1 ERROR 日志突增告警
- **计数**：loguru sink `_error_spike_sink`（注册于 `LogManager._setup()`）按滑动窗口统计每条 ERROR+，同步 `inc(django_error_logs_total)`。
- **阈值告警**：`core.tasks.check_error_spike`（每 5 分钟）读取窗口计数，超过 `ALERT_ERROR_SPIKE_THRESHOLD`（默认 50 / 300s 窗口）且过 `ALERT_ERROR_SPIKE_COOLDOWN`（默认 1h）则经 `alert_system` 告警。
- **跨进程聚合**：多进程部署下，单 beat 任务只能看到本进程错误；全局聚合由 Prometheus 规则 `DjangoErrorLogSpike`（`rate(django_error_logs_total[5m])`）完成。

### 7.2 慢查询 / 长事务监控
- **慢查询**：`framework/db/monitoring.py` 在 `DBPoolConfig.ready()` 全局 patch `CursorWrapper`，对每条 SQL 计时；超 `DB_SLOW_QUERY_THRESHOLD`（默认 1.0s）累计 `django_db_slow_queries_total` + 采样日志 + 节流告警（`DB_SLOW_QUERY_ALERT_COOLDOWN`）。指标跨进程由 Prometheus 规则 `DjangoSlowQuerySpike` 聚合。
- **长事务**：`core.tasks.check_long_transactions`（每 5 分钟）直接查 PostgreSQL `pg_stat_activity`（`xact_start` 超过 `DB_LONG_TX_THRESHOLD` 默认 30s），设置 `django_db_long_transactions` 并告警。非 PG 自动跳过。

### 7.3 安全扫描（`key_management.security_audit`，每日 03:10）
组合三项检查，任一风险经 `alert_system` 告警（渠道 `ALERT_SECURITY_CHANNELS`）：
- **TLS 证书到期**：`scan_certificates(paths=TLS_CERT_PATHS, warn_days=TLS_CERT_WARN_DAYS)` 解析 PEM/DER，剩余天数 < 阈值告警（用 `cryptography`，缺失降级 `ssl`）。
- **密钥泄漏**：`scan_secret_leaks(paths)` 启发式扫描 `apps/framework/extensions`（或 `SECRET_LEAK_SCAN_PATHS`）源码，匹配私钥头 / AWS Key / 硬编码 password/secret/api_key/token/JWT 等，仅上报文件:行 + 掩码片段，绝不输出真实密钥。
- **密钥年龄**：`check_key_age` 检查主密钥使用天数，`KEY_MAX_AGE_DAYS`（默认 90）超期告警。

### 7.4 每日系统健康日报（`core.tasks.daily_health_report`，每日 09:00）
汇总并推钉钉/飞书（开关 `DAILY_REPORT_DINGTALK` / `DAILY_REPORT_FEISHU`，需对应 webhook 已配）：
- ERROR 累计（本进程）、今日告警（总数/未解决/严重）、依赖健康、Celery 队列积压（经 `celery_app.control.inspect`）、DB 连接池指标（命中率/错误/超时）。
- 推送：钉钉 `DingTalkSendMsg().send_markdown`；飞书 `FeiShuTalkChatBot().send_text`。

### 7.5 相关配置（`settings/base.py`，均可用环境变量覆盖）
```
ALERT_ERROR_SPIKE_THRESHOLD / _WINDOW / _COOLDOWN / _CHANNELS
DB_SLOW_QUERY_THRESHOLD / _ALERT / _ALERT_COOLDOWN
DB_LONG_TX_ALIAS / DB_LONG_TX_THRESHOLD
TLS_CERT_PATHS / TLS_CERT_WARN_DAYS / SECRET_LEAK_SCAN_PATHS / KEY_MAX_AGE_DAYS / ALERT_SECURITY_CHANNELS
DAILY_REPORT_DINGTALK / DAILY_REPORT_FEISHU
```
示例 `.env`：
```
TLS_CERT_PATHS=["/etc/nginx/certs"]
ALERT_SECURITY_CHANNELS=["dingtalk"]
```

---

## 8. 后续可扩展（仍有空间）

- ERROR 日志突增 / 慢查询的跨进程聚合除 Prometheus 规则外，也可在 `alert_system` 内置规则里直接消费（目前依赖 Prometheus）。
- 密钥泄漏扫描可接入 CI 阶段（pre-commit / GitHub Action）做"提交前拦截"，与每日扫描互补。
- 健康日报可加入更多业务指标（限流拒绝率、WebSocket 在线峰值、租户配额使用率）。
