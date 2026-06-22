# WebSocket & Channels 部署指南

## 架构说明

本项目使用 Django Channels 实现 WebSocket 实时通信功能：

- **开发环境**：使用 `InMemoryChannelLayer`（内存存储）
- **生产环境**：使用 Redis 作为 Channel Layer 后端

## 生产环境配置

### 1. 环境变量配置

复制 `.env.prod.example` 为 `.env` 并修改配置：

```bash
cp .env.prod.example .env
```

关键配置项：

```env
# 必须启用 Redis
REDIS_ENABLED=True
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your_redis_password
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. Redis 服务器要求

确保 Redis 服务器正常运行：

```bash
# 检查 Redis
redis-cli ping

# 应该返回: PONG
```

## 部署方式

### 使用 Daphne (推荐)

Daphne 是 ASGI 服务器，专门为 Django Channels 设计：

```bash
# 安装 Daphne
pip install daphne

# 运行
daphne djangoProjectTest.asgi:application
```

### 使用 Gunicorn + Uvicorn

```bash
# 安装依赖
pip install gunicorn uvicorn

# 运行
gunicorn djangoProjectTest.asgi:application \
    -k uvicorn.workers.UvicornWorker \
    -w 4 \
    -b 0.0.0.0:8000
```

### 使用 Docker (生产推荐)

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  web:
    build: .
    command: daphne djangoProjectTest.asgi:application -b 0.0.0.0 -p 8000
    ports:
      - "8000:8000"
    environment:
      - ENV=PROD
      - REDIS_ENABLED=True
      - REDIS_HOST=redis
    depends_on:
      - redis
    env_file:
      - .env

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

## Nginx 配置

生产环境需要配置 Nginx 支持 WebSocket：

```nginx
upstream django {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # 静态文件
    location /static/ {
        alias /path/to/static/;
    }
    
    # 媒体文件
    location /media/ {
        alias /path/to/media/;
    }
}
```

## WebSocket 端点

| 端点 | 说明 | 认证要求 |
|------|------|----------|
| `/ws/core/chat/<room_name>/` | 聊天室 | 可选 |
| `/ws/core/notifications/` | 通知推送 | 必须登录 |

## 客户端示例

### JavaScript 连接

```javascript
// 连接聊天室
const chatSocket = new WebSocket(
    'wss://yourdomain.com/ws/core/chat/public/'
);

chatSocket.onmessage = function(e) {
    const data = JSON.parse(e.data);
    console.log('收到消息:', data);
};

// 发送消息
chatSocket.send(JSON.stringify({
    'type': 'chat',
    'message': 'Hello!'
}));
```

### 在后台发送通知

```python
from core.utils import send_user_notification

# 向用户 ID 为 1 的用户发送通知
send_user_notification(
    user_id=1,
    title="系统通知",
    message="你有一条新消息",
    data={"type": "chat"}
)
```

## 故障排查

### WebSocket 连接失败

1. 检查 Redis 是否正常运行
2. 检查 `REDIS_ENABLED` 是否设置为 `True`
3. 查看日志中是否有连接错误

### 认证失败

1. 确保用户已登录
2. 检查 Session 或 Token 是否有效
3. 通知通道需要认证用户才能连接

## 性能优化

1. **Redis 集群**：生产环境建议使用 Redis 集群
2. **连接池**：已配置 `REDIS_MAX_CONNECTIONS` 控制连接数
3. **Worker 数量**：根据服务器配置调整 ASGI worker 数量
