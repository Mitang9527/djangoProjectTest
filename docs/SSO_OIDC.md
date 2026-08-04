# 单点登录（SSO）— OIDC 接入指南

本项目通过 [mozilla-django-oidc](https://github.com/mozilla/mozilla-django-oidc) 接入 **OpenID Connect（OIDC）** 标准协议，
可对接任意支持 OIDC 的身份提供商（IdP），例如：

- **Keycloak**（自建 IdP，企业常用）
- **Auth0 / Okta**
- **Azure AD / Entra ID**
- **企业微信 / 飞书 / 钉钉**（均提供 OIDC 兼容端点）

## 方案概述

| 项 | 说明 |
|----|------|
| 协议 | OpenID Connect（基于 OAuth2 授权码流程 + PKCE 可选） |
| 角色 | 本系统作为 **SP（服务提供商）** 接入现有 IdP |
| 账号映射 | **自动建号**：首次登录按 `email` / `sub` 自动创建本地 User，并保留原有账号密码 / JWT 登录作为兜底 |
| Token 交付 | OIDC 回调完成后，后端签发 JWT（access + refresh），通过重定向 `?access=...&refresh=...` 交给前端 SPA |
| 依赖 | `mozilla-django-oidc>=4.0.0`（已写入 `requirements/base.txt`） |

## 启用步骤

### 1. 在 IdP 注册客户端（Relying Party）

在 IdP 后台创建应用，记录以下信息：
- **Client ID** / **Client Secret**
- **Redirect URI（回调地址）**：`https://<你的域名>/api/users/oidc/callback/`
- 授权流程：Authorization Code
-  scopes：`openid profile email`

从 IdP 的 **Discovery 文档**（`/.well-known/openid-configuration`）获取各端点：
`authorization_endpoint`、`token_endpoint`、`userinfo_endpoint`、`jwks_uri`。

### 2. 配置环境变量（`.env`）

```env
OIDC_ENABLED=True
OIDC_RP_CLIENT_ID=your-client-id
OIDC_RP_CLIENT_SECRET=your-client-secret
OIDC_OP_AUTHORIZATION_ENDPOINT=https://idp.example.com/auth
OIDC_OP_TOKEN_ENDPOINT=https://idp.example.com/token
OIDC_OP_USER_ENDPOINT=https://idp.example.com/userinfo
OIDC_OP_JWKS_ENDPOINT=https://idp.example.com/jwks
OIDC_OP_LOGOUT_ENDPOINT=https://idp.example.com/logout   # 可选
OIDC_RP_SIGN_ALGO=RS256          # IdP 用公钥(RS256/ES256)签名时；对称密钥用 HS256
OIDC_CREATE_USER=True            # False 则仅允许已绑定账号登录
OIDC_USERNAME_CLAIM=email        # 定位用户的主 claim；无 email 的 IdP 改为 sub
OIDC_FRONTEND_REDIRECT_URL=https://your-frontend.com/sso-callback
OIDC_LOGOUT_REDIRECT_URL=/
```

### 3. 安装依赖并启动

```bash
pip install -r requirements/base.txt
python manage.py migrate        # 本项目无需新增迁移（未引入新字段）
python manage.py runserver
```

## 登录流程

```
用户点击「使用企业账号登录」
   → GET /api/users/oidc/login/
   → 302 重定向到 IdP 授权页
   → 用户在 IdP 完成认证 / 授权
   → IdP 302 回调 /api/users/oidc/callback/（携带 code）
   → 后端用 code 换 token + 拉取 userinfo
   → 自动建号或绑定本地 User + 建立 Session 登录
   → 签发 JWT，302 重定向到 OIDC_FRONTEND_REDIRECT_URL?access=...&refresh=...
   → 前端存储 JWT，后续以 Authorization: Bearer <access> 调 API
```

登出：`GET /api/users/oidc/logout/`（清理本地 Session，若配置了 `OIDC_OP_LOGOUT_ENDPOINT` 则跳转 IdP 全局登出）。

## 前端集成要点

1. 在登录页放置「使用企业账号登录」按钮，指向 `/api/users/oidc/login/`。
2. 准备回调页（如 `/sso-callback`），读取 URL 中的 `access` / `refresh` 存入本地（localStorage / httpOnly cookie 由前端决定），随后跳转到首页。
3. 之后所有 API 请求携带 `Authorization: Bearer <access>`。

## 账号映射策略

- **查找顺序**：`email`（claims 中） → `sub`（IdP 唯一标识，兜底）。
- **自动建号**：未找到本地用户且 `OIDC_CREATE_USER=True` 时，以 `email` 前缀（或 `sub`）为用户名创建 User，填充 `nickname` / `email`。
- **保留密码登录**：`AUTHENTICATION_BACKENDS` 同时保留 `ModelBackend`，因此原有的账号密码登录、`/api/jwt/login/` 依然可用——SSO 是增强而非替代。

## 故障排查

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| 启动报 `ModuleNotFoundError: mozilla_django_oidc` | 依赖未装 | `pip install mozilla-django-oidc` |
| `OIDC_ENABLED=False` 时无 OIDC 路由 | 符合预期 | 设 `OIDC_ENABLED=True` 并重启 |
| 回调报 `redirect_uri 不匹配` | IdP 白名单未加 `/api/users/oidc/callback/` | 在 IdP 补登记 |
| 回调报 `Invalid token signature` | `OIDC_RP_SIGN_ALGO` 与实际不符 | 改为 IdP 使用的算法（通常 RS256） |
| 自动建号失败 | IdP 未返回 `email` | 将 `OIDC_USERNAME_CLAIM` 改为 `sub` |
| 重定向到前端后 URL 无 token | 未配置 `OIDC_FRONTEND_REDIRECT_URL` | 填入前端回调地址 |

## 安全建议

- 生产环境 **必须 HTTPS**（OIDC 传输 token，明文风险极高）。
- `OIDC_RP_CLIENT_SECRET` 通过 `.env` 注入，切勿提交到仓库。
- 若仅允许特定员工登录，设 `OIDC_CREATE_USER=False` 并预先在后台创建账号（用同一 `email`）绑定。
- 建议为 OIDC 回调路径配置独立限流（已在网关 throttle 覆盖）。
- 若 IdP 支持，启用 `PKCE` 进一步加固授权码流程。
