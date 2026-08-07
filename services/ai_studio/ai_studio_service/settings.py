"""
AI 创作工作室 — 独立服务配置。

关键设计：
- 身份解耦：本服务不维护用户表，仅校验主平台签发的 JWT（共享 SIGNING_KEY）。
  token 中的 user_id / username 直接作为业务归属标识。
- 全部依赖（数据库 / Redis / JWT 密钥 / CORS）均从环境变量读取，便于 Docker 部署。
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-change-me")
DEBUG = os.environ.get("DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h]

# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "channels",  # WebSocket / ASGI
    "ai_studio_app",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ai_studio_service.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ai_studio_service.wsgi.application"
ASGI_APPLICATION = "ai_studio_service.asgi.application"

# ---------------------------------------------------------------------------
# 数据库（默认 Postgres；USE_SQLITE=1 时切到 sqlite，便于本地无依赖验证）
# ---------------------------------------------------------------------------
if os.environ.get("USE_SQLITE"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "ai_studio"),
            "USER": os.environ.get("POSTGRES_USER", "ai_studio"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "ai_studio_pass"),
            "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }

# ---------------------------------------------------------------------------
# 密码哈希（服务内无注册，仅占位）
# ---------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# ---------------------------------------------------------------------------
# 国际化
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# JWT（与主平台共享 SIGNING_KEY 即可互相验签）
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY", SECRET_KEY),
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(os.environ.get("JWT_ACCESS_TTL_HOURS", "24"))),
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# CORS（前端跨域调用）
# ---------------------------------------------------------------------------
_cors = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]
CORS_ALLOW_CREDENTIALS = False

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "ai_studio_app.auth.ServiceJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "framework.drf.renderer.CustomRenderer",
    ),
}

# ---------------------------------------------------------------------------
# Celery（任务队列：默认 RabbitMQ，跨服务解耦）
# ---------------------------------------------------------------------------
# 默认连 docker-compose 内的 rabbitmq；本地可设 amqp://localhost:5672// 或 redis/memory 调试。
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "amqp://rabbitmq:5672//")
# 跨服务投递任务不依赖 result backend，关闭可减少依赖（需要回查结果可设 rpc://）
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", None)
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

# 任务路由：生成类任务固定进入 ai_studio.generate 队列
# （worker 启动需监听该队列：celery -A ai_studio_service worker -Q ai_studio.generate）
CELERY_TASK_ROUTES = {
    "ai_studio_app.tasks.generate_task": {"queue": "ai_studio.generate"},
    "ai_studio_app.tasks.handle_generation": {"queue": "ai_studio.generate"},
}


# ---------------------------------------------------------------------------
# Channels / WebSocket（结果主动查询通道）
# 前端连 WS 后，服务按 task_id 轮询库内结果并实时推送（生成由 Celery worker 完成）。
# 默认内存通道层即可（消费者自建轮询，无需跨进程 group_send）；
# 多 daphne 实例部署时设 AI_STUDIO_CHANNEL_REDIS=redis://host:6379/0 启用 Redis 通道层。
# ---------------------------------------------------------------------------
_AI_CHANNEL_REDIS = os.environ.get("AI_STUDIO_CHANNEL_REDIS")
if _AI_CHANNEL_REDIS:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [_AI_CHANNEL_REDIS]},
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

# 默认同步 mock 执行；AI_STUDIO_SYNC=False 时由 Celery worker 异步执行
AI_STUDIO_SYNC = os.environ.get("AI_STUDIO_SYNC", "1") == "1"

# 注册赠送额度（首次访问额度接口时自动发放）
AI_STUDIO_SIGNUP_GIFT = int(os.environ.get("AI_STUDIO_SIGNUP_GIFT", "50"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
