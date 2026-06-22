# Django 企业级架构项目

一个功能完整、架构规范的 Django 企业级项目模板，支持多种认证方式、实时通信、消息通知等功能。

## 🚀 功能特性

### 认证与权限
- ✅ **JWT 认证** - 支持 Access/Refresh Token 双令牌机制
- ✅ **Session 认证** - 用于 Web 页面访问
- ✅ **Token 黑名单** - 支持 JWT 登出失效
- ✅ **自定义用户模型** - 支持头像、昵称、角色等扩展字段

### 实时通信
- ✅ **WebSocket 支持** - 基于 Django Channels
- ✅ **聊天室** - 支持多人群聊
- ✅ **通知推送** - 实时消息通知
- ✅ **Redis 后端** - 生产环境支持

### 企业级功能
- ✅ **分环境配置** - base/dev/prod 三套配置
- ✅ **环境变量管理** - Pydantic 类型校验
- ✅ **日志管理** - Loguru 自动轮转
- ✅ **CORS 支持** - 前后端分离
- ✅ **API 文档** - Swagger/Redoc
- ✅ **多渠道通知** - 钉钉、飞书、企业微信、邮件
- ✅ **Redis 缓存** - 可配置的缓存层
- ✅ **RabbitMQ** - 消息队列支持

## 📁 项目结构

```
djangoProjectTest/
├── apps/                          # 应用目录
│   ├── core/                      # 核心应用
│   │   ├── consumers.py           # WebSocket 消费者
│   │   ├── utils.py               # WebSocket 工具
│   │   └── templates/core/        # 模板文件
│   ├── users/                     # 用户应用
│   │   ├── authentication.py      # 自定义认证
│   │   └── models.py              # 用户模型
│   └── soul/                      # 示例应用
├── djangoProjectTest/             # 项目配置
│   ├── settings/                  # 配置文件
│   │   ├── base.py                # 基础配置
│   │   ├── dev.py                 # 开发环境
│   │   └── prod.py                # 生产环境
│   ├── asgi.py                    # ASGI 配置 (WebSocket)
│   ├── wsgi.py                    # WSGI 配置
│   ├── urls.py                    # 主路由
│   ├── routing.py                 # WebSocket 路由
│   └── model.py                   # Pydantic 配置模型
├── utils/                         # 工具模块
│   ├── cache/                     # Redis 缓存
│   ├── queue/                     # RabbitMQ 队列
│   ├── logUtils/                  # 日志工具
│   ├── noticUtils/                # 通知工具
│   └── env_loader.py              # 统一环境加载工具
├── docs/                          # 文档目录
│   ├── JWT_AUTH.md                # JWT 认证文档
│   ├── WEBSOCKET_SETUP.md         # WebSocket 部署文档
│   └── PROJECT_AUDIT.md           # 项目审计报告
├── templates/                     # 全局模板
├── static/                        # 静态文件
├── media/                         # 媒体文件
├── logs/                          # 日志目录
├── manage.py                      # Django 管理脚本
├── requirements.txt               # 依赖列表（已清理）
└── .env.template                  # 环境变量配置模板
```

## 🛠️ 快速开始

### 1. 环境要求

- Python 3.10+
- Redis (可选，生产环境必需)

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境

```bash
# 复制配置模板
cp .env.template .env

# 编辑 .env 文件，根据需要修改配置
# Windows: copy .env.template .env
```

### 4. 数据库迁移

```bash
# 运行迁移（首次运行必须）
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser
```

### 5. 运行服务

#### 开发模式（HTTP 仅）

```bash
python manage.py runserver
```

#### 完整模式（HTTP + WebSocket）

```bash
# 安装 Daphne
pip install daphne

# 运行 ASGI 服务器
daphne djangoProjectTest.asgi:application
```

访问：http://localhost:8000

## ⚙️ 配置说明

### 环境变量

项目使用 `.env` 文件管理配置，主要配置项：

```env
# Django 核心
DEBUG=True
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1

# 数据库
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3

# Redis (用于缓存和 WebSocket)
REDIS_ENABLED=False
REDIS_HOST=localhost
REDIS_PORT=6379

# JWT
TOKEN_EXPIRE_HOURS=24
```

### 环境切换

通过 `ENV` 变量控制：

```bash
# 开发环境（默认）
ENV=DEV python manage.py runserver

# 生产环境
ENV=PROD python manage.py runserver
```

## 📡 API 文档

### 认证接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/users/register/` | POST | 用户注册 |
| `/api/users/login/` | POST | 传统登录 |
| `/api/users/api/jwt/login/` | POST | JWT 登录 |
| `/api/users/api/jwt/refresh/` | POST | 刷新 Token |
| `/api/users/api/jwt/logout/` | POST | JWT 登出 |
| `/api/users/logout/` | POST | 统一登出 |

### WebSocket 端点

| 端点 | 说明 |
|------|------|
| `/ws/core/chat/<room_name>/` | 聊天室 |
| `/ws/core/notifications/` | 通知推送 |

完整文档访问：http://localhost:8000/api/swagger/

## 🔧 项目优化

### 已完成的优化

1. ✅ **统一环境管理** - 创建 `.env.template` 和 `utils/env_loader.py`
2. ✅ **清理依赖文件** - 移除 `requirements.txt` 中的本地路径依赖
3. ✅ **添加 logs 和 static 目录** - 确保目录被 git 跟踪
4. ✅ **完善文档** - 补充 README 和项目审计报告

## 📚 详细文档

- [JWT 认证指南](docs/JWT_AUTH.md)
- [WebSocket 部署指南](docs/WEBSOCKET_SETUP.md)
- [项目审计报告](docs/PROJECT_AUDIT.md)

## 🤝 开发建议

1. **使用虚拟环境**

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

2. **代码格式化**
```bash
# 建议使用 black 或 ruff
pip install black
black .
```

3. **运行测试**
```bash
python manage.py test
```

## 📄 许可证

MIT License
