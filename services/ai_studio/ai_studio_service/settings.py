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
    "SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY") or (SECRET_KEY if DEBUG else None),
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(os.environ.get("JWT_ACCESS_TTL_HOURS", "24"))),
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# 安全护栏：生产环境强制使用独立的 JWT_SIGNING_KEY，禁止回退到 SECRET_KEY
# （须与主平台配置为相同值，本服务仅校验主平台签发的 JWT）
if not SIMPLE_JWT.get("SIGNING_KEY"):
    raise RuntimeError(
        "JWT_SIGNING_KEY 环境变量未设置。生产环境必须使用独立的 JWT 签名密钥，"
        "且须与主平台配置为相同值以实现跨服务验签。"
    )

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

# ---------------------------------------------------------------------------
# 日志：接入 loguru（与主平台 framework.log_utils 一致，含分文件落盘 + JSON）
# framework 未挂载到 PYTHONPATH 时自动降级为标准 logging，不阻断启动。
# ---------------------------------------------------------------------------
LOGS_DIR = os.path.join(BASE_DIR, "logs")
# 日志级别可由 LOG_LEVEL 环境变量覆盖（DEBUG/INFO/WARNING/ERROR），默认 DEBUG 模式为 DEBUG、否则 INFO
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()

try:
    from framework.log_utils.loguru_control import LogManager, InterceptHandler

    LogManager(log_dir=LOGS_DIR, level=LOG_LEVEL, debug=DEBUG)
    _HANDLERS = {"loguru": {"class": "framework.log_utils.loguru_control.InterceptHandler"}}
    _LOGGER_HANDLERS = ["loguru"]
except Exception:  # pragma: no cover - framework 不可用时降级
    _HANDLERS = {"console": {"class": "logging.StreamHandler"}}
    _LOGGER_HANDLERS = ["console"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": _HANDLERS,
    "loggers": {
        "django": {
            "handlers": _LOGGER_HANDLERS,
            "level": LOG_LEVEL,
            "propagate": True,
        },
        "django.server": {
            "handlers": _LOGGER_HANDLERS,
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": _LOGGER_HANDLERS,
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": _LOGGER_HANDLERS,
            "level": "WARNING",
            "propagate": False,
        },
        "django.template": {
            # 模板变量解析 DEBUG 刷屏，纯 API 后端不需要
            "handlers": _LOGGER_HANDLERS,
            "level": "WARNING",
            "propagate": False,
        },
        "django.utils.autoreload": {
            # runserver autoreload 每 tick 打 DEBUG 刷屏
            "handlers": [],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# =====================================================
# Sentry 错误追踪（可选：设置 SENTRY_DSN 后自动启用，未配置则跳过）
# =====================================================
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN and not DEBUG:
    try:
        from framework.core.sentry_init import init_sentry

        init_sentry()
    except Exception:  # pragma: no cover - Sentry 任何异常都不应阻断启动（init_sentry 内部已记录）
        pass
