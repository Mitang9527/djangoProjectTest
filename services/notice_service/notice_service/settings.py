"""
通知服务 — 独立服务配置。

关键设计：
- 无状态：不维护业务表，sqlite 仅作 Django 占位；通知发送结果不落库。
- 全部渠道配置（钉钉/飞书/企微 webhook、邮件 SMTP）从环境变量读取，便于 Docker 部署。
- 与主平台共享同一 RabbitMQ（CELERY_BROKER_URL），主平台把通知任务投递到
  notice.send 队列，本服务的 worker 消费后调用 notice_utils 渠道控制器分发。
"""
from __future__ import annotations

import os
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
    "notice_app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "notice_service.urls"

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

WSGI_APPLICATION = "notice_service.wsgi.application"
ASGI_APPLICATION = "notice_service.asgi.application"

# ---------------------------------------------------------------------------
# 数据库（无状态：sqlite 占位，不建业务表）
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# 服务内无注册，仅占位
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
# 通知渠道配置（来自环境变量，留空则对应渠道返回「未配置」错误）
# ---------------------------------------------------------------------------
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "")
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
FEISHU_SECRET = os.environ.get("FEISHU_SECRET", "")
WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK", "")

EMAIL_SEND_USER = os.environ.get("EMAIL_SEND_USER", "")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_STAMP_KEY = os.environ.get("EMAIL_STAMP_KEY", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true") == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "false") == "true"
EMAIL_SEND_LIST = os.environ.get("EMAIL_SEND_LIST", "")
EMAIL_SENDER_NAME = os.environ.get("EMAIL_SENDER_NAME", "Admin")

# ---------------------------------------------------------------------------
# DRF（仅用于 /api/notice/notify/ 轻量入口）
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_AUTHENTICATION_CLASSES": (),
    "DEFAULT_PERMISSION_CLASSES": (),
}

# ---------------------------------------------------------------------------
# Celery（任务队列：默认 RabbitMQ，与主平台共享 broker）
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "amqp://rabbitmq:5672//")
# 跨服务投递任务不依赖 result backend；需要回查结果可设 rpc://
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", None)
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"

# 任务路由：通知发送固定进入 notice.send 队列
# （worker 启动需监听该队列：celery -A notice_service worker -Q notice.send）
CELERY_TASK_ROUTES = {
    "notice_app.tasks.send_notification": {"queue": "notice.send"},
}

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
