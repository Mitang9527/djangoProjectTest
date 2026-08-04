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

class RabbitMQConfig(BaseModel):
    """RabbitMQ 配置"""
    host: str = Field("localhost", validation_alias=AliasChoices("RABBITMQ_HOST"))
    port: int = Field(5672, validation_alias=AliasChoices("RABBITMQ_PORT"))
    username: str = Field("guest", validation_alias=AliasChoices("RABBITMQ_USER"))
    password: str = Field("guest", validation_alias=AliasChoices("RABBITMQ_PASSWORD"))
    virtual_host: str = Field("/", validation_alias=AliasChoices("RABBITMQ_VHOST"))
    heartbeat: int = Field(300, validation_alias=AliasChoices("RABBITMQ_HEARTBEAT"))
    connection_attempts: int = Field(3, validation_alias=AliasChoices("RABBITMQ_ATTEMPTS"))
    retry_delay: int = Field(5, validation_alias=AliasChoices("RABBITMQ_RETRY_DELAY"))
    enabled: bool = Field(False, validation_alias=AliasChoices("RABBITMQ_ENABLED"))

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
    
    # Token 有效期（单位：小时），默认 24 小时
    TOKEN_EXPIRE_HOURS: int = 24

    # Refresh Token 有效期（单位：天），默认 1 天
    REFRESH_TOKEN_EXPIRE_DAYS: int = 1

    # 滑动会话（Sliding Session）：access token 临近过期时自动续期
    # 是否启用滑动续期（默认关闭，需前端配合读取 X-Access-Token 响应头）
    SLIDING_SESSION_ENABLED: bool = False
    # 触发续期的剩余有效期阈值（秒），默认 300 秒（5 分钟）
    SLIDING_REFRESH_THRESHOLD_SECONDS: int = 300

    # 会话空闲超时（秒）：已登录用户超过该时长无任何操作则强制登出；0 表示禁用
    SESSION_IDLE_TIMEOUT_SECONDS: int = 1800

    # 空闲超时排除路径前缀：这些路径不参与空闲计时（逗号分隔字符串或列表均可）。
    # 默认覆盖健康检查 / 静态 / 媒体 / 登录页 / SSO 流程，避免误踢或干扰探活。
    SESSION_IDLE_TIMEOUT_EXEMPT_PATHS: list[str] = Field(
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
    rabbitmq: RabbitMQConfig = Field(default_factory=RabbitMQConfig)

    # --- OIDC 单点登录配置（顶层字段，确保 OIDC_* 环境变量可直接注入）---
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

    model_config = SettingsConfigDict(
        # 不再自动加载 env_file，使用我们统一的 env_loader
        extra="ignore"
    )

# 实例化全局配置对象
try:
    global_config = ProjectSettings()
except Exception as e:
    logger.error(f"❌ 配置文件校验失败: {e}")
    raise e
