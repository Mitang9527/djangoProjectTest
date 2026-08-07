# JWT 认证使用指南

## 概述

本项目已集成 `djangorestframework-simplejwt` 提供 JWT (JSON Web Token) 认证功能。

## 安装依赖

```bash
pip install djangorestframework-simplejwt
```

## 数据库迁移

首次使用需要运行迁移：

```bash
python manage.py migrate
```

## API 接口

### 1. JWT 登录

**接口**: `POST /api/users/api/jwt/login/`

**请求参数**:
```json
{
  "username": "your_username",
  "password": "your_password"
}
```

**响应示例**:
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "user": {
    "id": 1,
    "username": "your_username",
    "email": "user@example.com",
    "nickname": "用户昵称",
    "role": "user"
  }
}
```

### 2. 刷新 Token

**接口**: `POST /api/users/api/jwt/refresh/`

**请求参数**:
```json
{
  "refresh": "your_refresh_token"
}
```

**响应示例**:
```json
{
  "access": "new_access_token"
}
```

### 3. 验证 Token

**接口**: `GET /api/users/api/jwt/verify/`

**请求头**:
```
Authorization: Bearer your_access_token
```

**响应示例**:
```json
{
  "valid": true,
  "user": {
    "id": 1,
    "username": "your_username",
    "email": "user@example.com",
    "role": "user"
  }
}
```

### 4. JWT 登出

**接口**: `POST /api/users/api/jwt/logout/`

**请求头**:
```
Authorization: Bearer your_access_token
```

**请求参数**:
```json
{
  "refresh": "your_refresh_token"
}
```

## Token 有效期

所有有效期均可通过环境变量配置，无需改代码：

| 令牌 | 配置项 | 默认值 | 说明 |
|------|--------|--------|------|
| Access Token | `TOKEN_EXPIRE_HOURS` | 24 小时 | 过期即失效，可被黑名单吊销 |
| Refresh Token | `REFRESH_TOKEN_EXPIRE_DAYS` | 1 天 | 开启轮换 + 黑名单，旧 token 用一次即失效 |

### 滑动过期（Sliding Session）

当 `SLIDING_SESSION_ENABLED=True` 时，若 access token 剩余有效期低于
`SLIDING_REFRESH_THRESHOLD_SECONDS`（默认 300 秒）且用户仍在活跃访问，
服务端会自动签发一个新的 access token，并通过响应头返回：

```
X-Access-Token: <new_access_token>
X-Token-Refreshed: true
```

前端检测到 `X-Access-Token` 响应头后，用它覆盖本地存储的 token 即可实现
**活跃会话自动续期**——用户无需重新登录，也无需改动登录/刷新流程。
用户静默超过 refresh token 有效期（默认 1 天）后，才需要重新登录。

> 滑动续期仅基于已验证 token 的声明生成新 token，无额外数据库查询；
> 若签发失败会被静默忽略，不影响正常认证。

## 使用 Token 认证方式

### 方式一：HTTP 请求头

```
Authorization: Bearer <your_access_token>
```

### 方式二：JWT 前缀

```
Authorization: JWT <your_access_token>
```

## 配置说明

JWT 相关配置在 `djangoProjectTest/settings/base.py` 中的 `SIMPLE_JWT` 配置项中。

### 环境变量配置：

```env
# Access Token 有效期（小时）
TOKEN_EXPIRE_HOURS=24

# Refresh Token 有效期（天）
REFRESH_TOKEN_EXPIRE_DAYS=1

# 滑动会话：access token 临近过期时自动续期
SLIDING_SESSION_ENABLED=False
# 触发续期的剩余有效期阈值（秒）
SLIDING_REFRESH_THRESHOLD_SECONDS=300
```

## 与原有认证方式

项目同时保留了原有的 Token 认证方式，您可以根据需要选择使用：

1. **JWT 认证**（推荐）：使用 `Authorization: Bearer <token>`
2. **Token 认证**：使用 `Authorization: Token <token>`
3. **Session 认证**：用于 Web 页面

## 示例：使用 JWT 访问受保护接口

```python
import requests

# 1. 登录获取 Token
login_response = requests.post(
    'http://localhost:8000/api/users/api/jwt/login/',
    json={
        'username': 'testuser',
        'password': 'testpass123'
    }
)
tokens = login_response.json()
access_token = tokens['access']

# 2. 使用 Token 访问受保护接口
response = requests.get(
    'http://localhost:8000/api/users/info/',
    headers={
        'Authorization': f'Bearer {access_token}'
    }
)
print(response.json())

## 会话空闲超时（Session Idle Timeout）

除了 JWT 的过期策略，**浏览器页面 / Web 会话（Session）** 现在支持"不动就退"的
空闲超时，与 Django 原生的 `SESSION_COOKIE_AGE`（绝对过期）语义不同：

- `SESSION_COOKIE_AGE = 7 天`：硬上限——无论活跃与否，登录满 7 天强制退出（兜底）。
- `SESSION_IDLE_TIMEOUT_SECONDS = 1800`（默认 30 分钟）：**空闲超时**——已登录用户
  超过该时长**没有任何操作**则立即销毁会话、强制重新登录。

### 行为细节

| 场景 | 结果 |
|------|------|
| 用户持续操作（每次请求间隔 < 阈值） | 会话保持活跃，时间戳不断刷新 |
| 用户离开超过 30 分钟再操作 | 当前请求被拒绝：API 返回 `401 {"detail": "Session idle timeout..."}`，页面重定向到 `/admin/login/` |
| 完全不动但 < 30 分钟 | 仍在线（空闲超时未到） |
| 登录满 7 天（无论活跃与否） | 被 `SESSION_COOKIE_AGE` 兜底强制退出 |
| 健康检查 `/api/health*`、静态、登录页、OIDC 流程 | 不参与空闲计时，不会被误踢 |

### 配置

```env
# 会话空闲超时（秒）；0 表示禁用（即退回到仅 SESSION_COOKIE_AGE 绝对过期）
SESSION_IDLE_TIMEOUT_SECONDS=1800

# 空闲超时排除路径前缀（逗号分隔）；这些路径不参与空闲计时，默认已覆盖
# 健康检查/静态/媒体/登录页/SSO，通常无需修改，可在此追加自定义路径
SESSION_IDLE_TIMEOUT_EXEMPT_PATHS=/api/health,/static,/media,/admin/login,/api/users/login,/api/users/oidc,/favicon.ico

# 页面请求空闲超时后的重定向地址（API 请求始终返回 401，不受此影响）
SESSION_IDLE_TIMEOUT_REDIRECT_URL=/admin/login/
```

> 说明：空闲超时由 `framework.security.idle_timeout.IdleTimeoutMiddleware` 实现，
> 已注册在 `AuthenticationMiddleware` 之后。排除路径与重定向地址均可通过上述环境变量
> 覆盖（逗号分隔字符串或列表均可）。它只影响 **Session 登录态**（浏览器页面 /
> Django admin）；**JWT（API）** 无状态不受影响，其"不动就退"由 access 24h + refresh 1天
> 的绝对/滑动过期语义覆盖（如需更短的 JWT 空闲窗口，请调小 `TOKEN_EXPIRE_HOURS` 或关闭滑动续期）。

## 安全建议

1. **生产环境使用 HTTPS**
2. 妥善保管 Refresh Token
3. 建议在客户端安全存储 Token（推荐 HttpOnly Cookie + 前端读取 X-Access-Token 响应头更新）
4. 定期更换 SECRET_KEY 与 JWT_SIGNING_KEY
5. 已内置滑动过期机制（`SLIDING_SESSION_ENABLED`），可避免频繁重新登录；若不使用，前端应在 access token 过期后用 refresh token 主动换新
