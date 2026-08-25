"""
测试环境配置
- SQLite 内存数据库
- Redis/Celery 禁用
- 密码哈希使用最快算法 (提升测试速度)
- 邮件使用内存后端
"""
import os

# 注意：pytest-django 4.x 会在根 conftest.py 导入之前就加载 settings
# （pytest_load_initial_conftests 钩子），因此测试环境变量必须在 settings
# 模块自身兜底，不能只依赖 conftest.py 的 setdefault。
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only-at-least-10-chars")
os.environ.setdefault("JWT_SIGNING_KEY", "test-jwt-signing-key-independent-from-secret-key-at-least-10c")
os.environ.setdefault("API_SECRET_KEY", "test-api-secret-key-not-for-production-use-at-least-10-chars")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("ENV", "TEST")
os.environ.setdefault("PROJECT_NAME", "DjangoTest")
os.environ.setdefault("TESTER_NAME", "Pytest")
os.environ.setdefault("ALLOWED_HOSTS", "*")

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

# 读写分离：测试环境默认不配置 DB_REPLICA_URL，install_replica 无副作用，
# 保持内存 SQLite 单库，保证 pytest 可跑。
from framework.db.replica import install_replica  # noqa: E402

DATABASES, DATABASE_ROUTERS = install_replica(DATABASES, DATABASE_ROUTERS)

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
