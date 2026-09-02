import sys
from pathlib import Path
from typing import List, Optional, Any

from loguru import logger
from pydantic import BaseModel, Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class ProjectConfig(BaseModel):
    """项目基础信息"""
    name: str = Field("DjangoProject", validation_alias=AliasChoices("PROJECT_NAME"))
    tester: str = Field("Admin", validation_alias=AliasChoices("TESTER_NAME"))
    env: str = Field("TEST", validation_alias=AliasChoices("ENV"))

class DatabaseConfig(BaseModel):
    """数据库配置"""
    engine: str = Field("django.db.backends.sqlite3", validation_alias=AliasChoices("DB_ENGINE"))
    name: str = Field("db.sqlite3", validation_alias=AliasChoices("DB_NAME"))
    user: Optional[str] = Field(None, validation_alias=AliasChoices("DB_USER"))
    password: Optional[str] = Field(None, validation_alias=AliasChoices("DB_PASSWORD"))
    host: Optional[str] = Field(None, validation_alias=AliasChoices("DB_HOST"))
    port: Optional[str] = Field(None, validation_alias=AliasChoices("DB_PORT"))

class DingTalkConfig(BaseModel):
    """钉钉配置"""
    webhook: str = Field("", validation_alias=AliasChoices("DINGTALK_WEBHOOK"))
    secret: str = Field("", validation_alias=AliasChoices("DINGTALK_SECRET"))

class FeiShuConfig(BaseModel):
    """飞书配置"""
    webhook: str = Field("", validation_alias=AliasChoices("FEISHU_WEBHOOK"))
    secret: str = Field("", validation_alias=AliasChoices("FEISHU_SECRET"))

class LarkConfig(BaseModel):
    """Lark 配置"""
    webhook: str = Field("", validation_alias=AliasChoices("LARK_WEBHOOK"))

class EmailConfig(BaseModel):
    """邮件配置"""
    send_user: str = Field("", validation_alias=AliasChoices("EMAIL_SEND_USER"))
    host: str = Field("smtp.qq.com", validation_alias=AliasChoices("EMAIL_HOST"))
    stamp_key: str = Field("", validation_alias=AliasChoices("EMAIL_STAMP_KEY"))
    send_list: str = Field("", validation_alias=AliasChoices("EMAIL_SEND_LIST"))

class WeChatConfig(BaseModel):
    """企业微信配置"""
    webhook: str = Field("", validation_alias=AliasChoices("WECHAT_WEBHOOK"))

class RedisConfig(BaseModel):
    """Redis 配置"""
    host: str = Field("localhost", validation_alias=AliasChoices("REDIS_HOST"))
    port: int = Field(6379, validation_alias=AliasChoices("REDIS_PORT"))
    db: int = Field(0, validation_alias=AliasChoices("REDIS_DB"))
    password: Optional[str] = Field(None, validation_alias=AliasChoices("REDIS_PASSWORD"))
    max_connections: int = Field(100, validation_alias=AliasChoices("REDIS_MAX_CONNECTIONS"))
    socket_connect_timeout: int = Field(5, validation_alias=AliasChoices("REDIS_CONNECT_TIMEOUT"))
    socket_timeout: int = Field(10, validation_alias=AliasChoices("REDIS_TIMEOUT"))
    enabled: bool = Field(False, validation_alias=AliasChoices("REDIS_ENABLED"))


class OSSConfig(BaseModel):
    """对象存储（OSS）配置。

    支持 local(默认)/aliyun/s3(MinIO·COS·OBS 兼容)；仅当 enabled=True 且 backend!=local 时连云端，否则回退本地。
    """
    enabled: bool = Field(False, validation_alias=AliasChoices("OSS_ENABLED"))
    #: local | aliyun | s3（s3 兼容 MinIO/COS/OBS）
    backend: str = Field("local", validation_alias=AliasChoices("OSS_BACKEND"))
    bucket: str = Field("", validation_alias=AliasChoices("OSS_BUCKET"))
    #: 阿里云=外网/内网域名；s3=endpoint_url（含或不含 http(s):// 均可）
    endpoint: str = Field("", validation_alias=AliasChoices("OSS_ENDPOINT"))
    region: str = Field("", validation_alias=AliasChoices("OSS_REGION"))
    access_key: str = Field("", validation_alias=AliasChoices("OSS_ACCESS_KEY"))
    secret_key: str = Field("", validation_alias=AliasChoices("OSS_SECRET_KEY"))
    use_ssl: bool = Field(True, validation_alias=AliasChoices("OSS_USE_SSL"))
    #: 绑定的自定义域名/CDN，公开对象优先使用
    custom_domain: str = Field("", validation_alias=AliasChoices("OSS_CUSTOM_DOMAIN"))
    #: 签名 URL 有效期（秒）
    url_expire: int = Field(3600, validation_alias=AliasChoices("OSS_URL_EXPIRE"))
    #: 本地后端根目录（相对 BASE_DIR），仅 backend=local 生效
    local_root: str = Field("media/oss", validation_alias=AliasChoices("OSS_LOCAL_ROOT"))
    #: 公开对象访问基础 URL（如 CDN 绝对地址），覆盖默认 media URL
    public_base_url: str = Field("", validation_alias=AliasChoices("OSS_PUBLIC_BASE_URL"))

class NotificationConfig(BaseModel):
    """通知配置"""
    # 使用 Any 绕过 pydantic-settings 的强制 JSON 解析
    notification_type: Any = Field(default=[0], validation_alias=AliasChoices("NOTIFICATION_TYPE"))

    @field_validator("notification_type", mode="before")
    @classmethod
    def parse_notification_type(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return [0]
            try:
                return [int(x.strip()) for x in v.split(",") if x.strip()]
            except ValueError:
                raise ValueError("NOTIFICATION_TYPE 必须是逗号分割的数字字符串，例如 '1, 2'")
        return v

class ProjectSettings(BaseSettings):
    """全局项目配置校验模型"""
    
    # Django 核心配置
    DEBUG: bool = False
    SECRET_KEY: str = Field(..., min_length=10)
    
    # JWT 签名密钥（独立于 SECRET_KEY，生产环境必须单独设置）
    JWT_SIGNING_KEY: str = Field("", validation_alias=AliasChoices("JWT_SIGNING_KEY"))
    
    # Token 有效期（单位：小时），默认 1 小时
    TOKEN_EXPIRE_HOURS: int = 1

    # Refresh Token 有效期（单位：天），默认 1 天
    REFRESH_TOKEN_EXPIRE_DAYS: int = 1

    # 滑动会话：access token 临近过期自动续期（默认关闭，需前端配合读取 X-Access-Token 响应头）
    SLIDING_SESSION_ENABLED: bool = False
    # 触发续期的剩余有效期阈值（秒），默认 300 秒（5 分钟）
    SLIDING_REFRESH_THRESHOLD_SECONDS: int = 300

    # 会话空闲超时（秒）：超时无操作强制登出；0 表示禁用
    SESSION_IDLE_TIMEOUT_SECONDS: int = 1800

    # 空闲超时排除路径前缀（逗号分隔字符串或列表均可）；默认覆盖健康检查/静态/媒体/登录页/SSO，避免误踢或干扰探活。
    # ⚠️ 类型必须是 Any 而非 list[str]（与 ALLOWED_HOSTS / CORS_ALLOWED_ORIGINS 一致）：
    # 声明为 list[str] 时 pydantic-settings 会先对环境变量做 JSON 解码，逗号分隔字符串
    # （如 "/api/health,/static"）会抛 JSONDecodeError 直接阻断启动；用 Any 让下方 validator 正常拆分。
    SESSION_IDLE_TIMEOUT_EXEMPT_PATHS: Any = Field(
        default_factory=lambda: [
            "/api/health",
            "/static",
            "/media",
            "/admin/login",
            "/api/users/login",
            "/api/users/oidc",
            "/favicon.ico",
        ]
    )

    # 页面请求空闲超时后的重定向地址（API 请求始终返回 401，不受此影响）
    SESSION_IDLE_TIMEOUT_REDIRECT_URL: str = "/admin/login/"

    @field_validator("SESSION_IDLE_TIMEOUT_EXEMPT_PATHS", mode="before")
    @classmethod
    def parse_exempt_paths(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    # 使用 Any 绕过 pydantic-settings 的强制 JSON 解析
    ALLOWED_HOSTS: Any = Field(default=["*"])
    
    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    # 跨域允许域名（生产环境使用）
    CORS_ALLOWED_ORIGINS: Any = Field(default=[])

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    # 嵌套配置组
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ding_talk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    feishu: FeiShuConfig = Field(default_factory=FeiShuConfig)
    lark: LarkConfig = Field(default_factory=LarkConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    wechat: WeChatConfig = Field(default_factory=WeChatConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    oss: OSSConfig = Field(default_factory=OSSConfig)

    # OIDC 单点登录配置（顶层字段，确保 OIDC_* 环境变量可直接注入）
    OIDC_ENABLED: bool = Field(False, validation_alias=AliasChoices("OIDC_ENABLED"))
    OIDC_RP_CLIENT_ID: str = Field("", validation_alias=AliasChoices("OIDC_RP_CLIENT_ID"))
    OIDC_RP_CLIENT_SECRET: str = Field("", validation_alias=AliasChoices("OIDC_RP_CLIENT_SECRET"))
    OIDC_OP_AUTHORIZATION_ENDPOINT: str = Field("", validation_alias=AliasChoices("OIDC_OP_AUTHORIZATION_ENDPOINT"))
    OIDC_OP_TOKEN_ENDPOINT: str = Field("", validation_alias=AliasChoices("OIDC_OP_TOKEN_ENDPOINT"))
    OIDC_OP_USER_ENDPOINT: str = Field("", validation_alias=AliasChoices("OIDC_OP_USER_ENDPOINT"))
    OIDC_OP_JWKS_ENDPOINT: str = Field("", validation_alias=AliasChoices("OIDC_OP_JWKS_ENDPOINT"))
    OIDC_OP_LOGOUT_ENDPOINT: str = Field("", validation_alias=AliasChoices("OIDC_OP_LOGOUT_ENDPOINT"))
    OIDC_RP_SIGN_ALGO: str = Field("RS256", validation_alias=AliasChoices("OIDC_RP_SIGN_ALGO"))
    OIDC_CREATE_USER: bool = Field(True, validation_alias=AliasChoices("OIDC_CREATE_USER"))
    OIDC_USERNAME_CLAIM: str = Field("email", validation_alias=AliasChoices("OIDC_USERNAME_CLAIM"))
    OIDC_FRONTEND_REDIRECT_URL: str = Field("", validation_alias=AliasChoices("OIDC_FRONTEND_REDIRECT_URL"))
    OIDC_LOGOUT_REDIRECT_URL: str = Field("", validation_alias=AliasChoices("OIDC_LOGOUT_REDIRECT_URL"))
    
    # 安全配置
    SECURE_SSL_REDIRECT: bool = False

    # API 网关限流配置
    # 速率格式：次数/周期（s|m|h|d），如 "1000/h"；留空回退代码默认值。
    # 优先级：路由级 APILimitRule > 套餐 > 租户 > 此处全局默认。
    GATEWAY_THROTTLE_RATE_IP: str = "1000/h"
    GATEWAY_THROTTLE_RATE_USER: str = "500/h"
    GATEWAY_THROTTLE_RATE_TENANT: str = "10000/h"
    GATEWAY_THROTTLE_RATE_ANON: str = "60/m"
    GATEWAY_THROTTLE_RATE_ENDPOINT: str = "100/h"
    # Redis 故障时限流策略：False=fail-closed（拒绝 429）；True=fail-open（降级放行）。默认 False。
    GATEWAY_THROTTLE_REDIS_FAIL_OPEN: bool = False

    # 登录限流（IP + 用户名双维度防暴力破解，对齐 Fast-Vben-Admin login.py）：窗口内失败达阈值
    # 即锁定该 IP/用户名 BLOCK_SECONDS 秒；登录成功自动清零；留空/0 回退默认值。
    LOGIN_RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    LOGIN_RATE_LIMIT_BLOCK_SECONDS: int = 900

    # 注册限流（IP 维度防批量刷注册）：窗口内注册次数（成功/失败均计）达阈值锁定该 IP。
    # ⚠️ 注册成功【不】清零（否则批量开号脚本每成功一次即清零、永远到不了阈值）；锁随窗口过期自然解除；
    # 与登录限流同 fail-open 策略，键前缀独立（ratelimit:register:*）。
    REGISTER_RATE_LIMIT_ENABLED: bool = True
    REGISTER_RATE_LIMIT_MAX_ATTEMPTS: int = 10
    REGISTER_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    REGISTER_RATE_LIMIT_BLOCK_SECONDS: int = 3600
    # 密码重置请求限流（IP + email 双维度防邮件轰炸/防枚举）：窗口内重置请求（成功/失败/用户不存在均计）
    # 达阈值锁定该 IP/email。⚠️ 成功【不】清零（防批量探测邮箱轰炸），锁随窗口过期自然解除；Redis 故障 fail-open。
    PASSWORD_RESET_RATE_LIMIT_ENABLED: bool = True
    PASSWORD_RESET_RATE_LIMIT_MAX_ATTEMPTS: int = 5
    PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    PASSWORD_RESET_RATE_LIMIT_BLOCK_SECONDS: int = 3600
    # 找回密码邮件中的重置页地址（前端路由）；为空时邮件只含 token 与使用说明（纯 API 对接场景）。
    PASSWORD_RESET_FRONTEND_URL: str = ""
    # 重置 token 有效期（秒），透传给 PasswordResetTokenGenerator（默认 30 分钟）
    PASSWORD_RESET_TIMEOUT_SECONDS: int = 1800
    # OAuth2 第三方登录（Authorization Code + PKCE）：回调成功后重定向的前端地址，为空则回调
    # 直接返回 JSON（access/refresh），由前端回调页 fetch 处理（对齐 OIDC 行为）。
    OAUTH2_FRONTEND_REDIRECT_URL: str = ""
    # state 有效期（秒）：授权链接生成到回调消费的窗口，过期后 state 作废（默认 10 分钟）
    OAUTH2_STATE_TTL: int = 600
    # 第三方账号 email 命中本地既有用户时自动绑定（默认开）；关闭后仅允许自动建号或已显式绑定的账号登录。
    OAUTH2_AUTO_BIND_EMAIL: bool = True
    # 第三方账号未匹配任何本地用户时自动建号（默认开，对齐 OIDC_CREATE_USER）
    OAUTH2_AUTO_CREATE_USER: bool = True
    # MFA TOTP：二维码/otpauth URI 的发行者名称；valid_window 为容忍时钟偏移的 30s 步数
    MFA_TOTP_ISSUER: str = "Django Enterprise Platform"
    MFA_TOTP_VALID_WINDOW: int = 1
    # 日志保留 TTL（天数）：审计/登录/操作日志归档清理（manage.py cleanup_logs 消费）；
    # created_at 早于 now-TTL 的记录会被删除；AuditLog 删除后自动重置链根保持哈希链自洽。
    AUDIT_LOG_TTL_DAYS: int = 180
    LOGIN_LOG_TTL_DAYS: int = 90
    OPERATION_LOG_TTL_DAYS: int = 90
    model_config = SettingsConfigDict(
        # 不再自动加载 env_file，使用我们统一的 env_loader
        extra="ignore"
    )

try:
    global_config = ProjectSettings()
except Exception as e:
    logger.error(f"❌ 配置文件校验失败: {e}")
    raise e
