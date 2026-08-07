"""
测试环境配置
- SQLite 内存数据库
- Redis/Celery 禁用
- 密码哈希使用最快算法 (提升测试速度)
- 邮件使用内存后端
"""
from .base import *  # noqa: F401, F403

DEBUG = False

# =====================================================
# 数据库：SQLite 内存
# =====================================================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# =====================================================
# 缓存：本地内存（不依赖 Redis）
# =====================================================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

# =====================================================
# Channel Layer：内存（不依赖 Redis）
# =====================================================
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# =====================================================
# Session：数据库后端（不依赖 Redis）
# =====================================================
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# =====================================================
# 密码哈希：使用最快算法（测试不需要安全哈希）
# =====================================================
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# =====================================================
# 邮件：内存后端（不实际发送）
# =====================================================
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# =====================================================
# 禁用 ORM 查询缓存（避免测试数据不一致）
# =====================================================
CACHALOT_ENABLED = False

# =====================================================
# 禁用 Celery 异步执行（任务同步执行）
# =====================================================
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# =====================================================
# 禁用限流（避免测试中被限流）
# =====================================================
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {},
}

# =====================================================
# 禁用 API 签名验证（测试中不验证签名）
# =====================================================
API_SIGNATURE_ENABLED = False

# =====================================================
# 禁用 Sentry（测试不上报）
# =====================================================
SENTRY_DSN = ""

# =====================================================
# 测试专用密钥
# =====================================================
SECRET_KEY = "test-secret-key-not-for-production-use-only"

# =====================================================
# 禁用安全重定向（测试环境不需要 HTTPS）
# =====================================================
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
