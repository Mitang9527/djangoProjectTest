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

- **Access Token**: 24 小时（可通过 `TOKEN_EXPIRE_HOURS` 环境变量配置）
- **Refresh Token**: 7 天

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
# Token 有效期（小时）
TOKEN_EXPIRE_HOURS=24
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
```

## 安全建议

1. **生产环境使用 HTTPS
2. 妥善保管 Refresh Token
3. 建议在客户端安全存储 Token
4. 定期更换 SECRET_KEY
5. 考虑 Token 自动刷新机制
