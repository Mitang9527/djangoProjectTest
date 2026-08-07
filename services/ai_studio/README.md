# AI 创作工作室 — 独立服务

将原有的 `apps/business/ai_studio` 抽取为**可独立部署**的 Django 服务，便于单独扩缩容、独立打包进 Docker。

## 设计要点

- **身份解耦**：本服务**不维护用户表**。它只信任主平台签发的 JWT（与主平台共享
  `JWT_SIGNING_KEY`），从 token 的 `user_id` / `username` 声明构造轻量 `AuthUser`
  作为 `request.user`。用户注册/登录全部由主平台 SSO 负责。
- **额度即注册赠送**：用户首次访问额度接口时，`get_or_create_quota` 自动发放
  `AI_STUDIO_SIGNUP_GIFT`（默认 50）额度，取代原来的「注册送额度」逻辑。
- **冻结-确认扣减**：创建任务先冻结额度，成功确认扣减、失败返还，流水不可变（对账用）。
- **生成后端可替换**：`services.run_mock_generation` 当前产出占位 SVG；接入真实模型
  （SDXL / 可灵 / 极睿等）时只替换该函数即可。
- **同步/异步可选**：`AI_STUDIO_SYNC=1`（默认）在请求内同步 mock；设为 `0` 则由
  Celery `worker` 异步执行，请求立即返回 `PENDING`。

## 目录结构

```
services/ai_studio/
├── manage.py
├── ai_studio_service/      # Django 工程包（settings / urls / wsgi / celery）
├── ai_studio_app/          # 业务 app（auth / models / services / views / tasks）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── .env.example
```

## 接口（挂载于 /api/v1/）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/generate/` | 创建生成任务 |
| GET  | `/api/v1/quota/` | 查询当前用户额度 |
| GET  | `/api/v1/tasks/` | 查询当前用户任务列表 |
| GET  | `/health/` | 健康检查 |

所有响应统一为 5 字段结构：`{status, code, message, data, errors}`。

## 本地运行（SQLite，无需装数据库）

```bash
cd services/ai_studio
export USE_SQLITE=1
export DJANGO_SECRET_KEY=dev-secret
export JWT_SIGNING_KEY=dev-jwt-secret
python manage.py migrate
python manage.py runserver 8000
```

## Docker 部署

```bash
cd services/ai_studio
cp .env.example .env
# 修改 .env 中的 JWT_SIGNING_KEY 与主平台一致
docker compose --env-file .env up --build
```

- `api`    : `gunicorn` 提供 `/api/v1/`
- `worker` : `celery` 消费生成任务（需 `AI_STUDIO_SYNC=0`）
- `redis`  : broker / result backend
- `postgres`: 业务库

## 跨服务鉴权对接

前端从主平台拿到 JWT 后，请求本服务时在 `Authorization: Bearer <token>` 中携带即可。
本服务用同一把 `JWT_SIGNING_KEY` 验签，并把 `user_id` 作为业务归属键。只要两边密钥一致、
token 含 `user_id` 声明，即可无缝互通。
