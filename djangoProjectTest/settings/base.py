import os
import sys
import re
from pathlib import Path
from ..model import global_config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Add apps & extensions directories to sys.path (both are import roots)
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))
sys.path.insert(0, os.path.join(BASE_DIR, 'extensions'))

# --- 核心配置 (通过 Pydantic 校验) ---
SECRET_KEY = global_config.SECRET_KEY
DEBUG = global_config.DEBUG
ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# Application definition
# Django 自带应用
SHARED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

# --- 自动发现 LOCAL_APPS（支持分类子目录，如 apps/system/、apps/business/）---
def _iter_app_modules(apps_dir, max_depth=2):
    """递归查找含 apps.py 的目录，返回相对于 apps_dir 的点分模块路径。"""
    modules = []
    if not os.path.isdir(apps_dir):
        return modules
    for root, dirs, files in os.walk(apps_dir):
        depth = root[len(apps_dir):].count(os.sep)
        if depth > max_depth:
            dirs[:] = []   # 超过最大深度则剪枝
            continue
        if 'apps.py' in files:
            rel = os.path.relpath(root, apps_dir)
            modules.append(rel.replace(os.sep, '.'))
    return modules


def discover_local_apps(apps_dir):
    local_apps = []
    for mod in _iter_app_modules(apps_dir):
        apps_file = os.path.join(apps_dir, *mod.split('.'), 'apps.py')
        try:
            with open(apps_file, 'r', encoding='utf-8') as f:
                content = f.read()
            # 使用正则匹配继承自 AppConfig 的类名
            match = re.search(r'class\s+(\w+)\(AppConfig\):', content)
            if match:
                config_class = match.group(1)
            else:
                # 备选方案：如果正则没匹配到，尝试传统的首字母大写
                config_class = f"{mod.split('.')[-1].capitalize()}Config"
        except Exception:
            # 容错处理
            config_class = f"{mod.split('.')[-1].capitalize()}Config"
        local_apps.append(f"{mod}.apps.{config_class}")
    return local_apps

EXTENSIONS_DIR = os.path.join(BASE_DIR, 'extensions')
LOCAL_APPS = discover_local_apps(os.path.join(BASE_DIR, 'apps')) + discover_local_apps(EXTENSIONS_DIR)

# 第三方库 app
THIRD_PARTY_APPS = [
    'rest_framework',   # 开发 REST API
    # 'rest_framework.authtoken',     # Token 认证
    'rest_framework_simplejwt',     # JWT 认证
    'rest_framework_simplejwt.token_blacklist',  # JWT 黑名单
    'channels',  # WebSocket 支持
    'django_filters',   #接口过滤
    'corsheaders',     #解决前后端跨域
    'drf_spectacular',  # Swagger 文档生成
    'django_extensions',  # Django 扩展工具
    'django_celery_beat',  # Celery 定时任务
    'cachalot',  # ORM 查询自动缓存
    'django_prometheus',  # Prometheus 指标监控
    'mozilla_django_oidc',  # OIDC 单点登录（SSO）
]

# 自定义用户模型
AUTH_USER_MODEL = 'users.User'

INSTALLED_APPS = SHARED_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    # 1. 全局指标采集（必须成对出现，且包裹所有逻辑）
    'django_prometheus.middleware.PrometheusBeforeMiddleware',

    # 2. 链路追踪（尽早生成 Request-ID，供后续所有中间件和日志使用）
    'framework.log_utils.request_id.RequestIDMiddleware',

    # 3. 安全与重定向（最外层的安全防护）
    'django.middleware.security.SecurityMiddleware',

    # 4. 静态文件托管（必须在 CommonMiddleware 之前，避免被重定向拦截）
    'whitenoise.middleware.WhiteNoiseMiddleware',

    # 5. 跨域处理（必须在任何可能生成响应的中间件之前）
    'corsheaders.middleware.CorsMiddleware',

    # 6. 会话管理
    'django.contrib.sessions.middleware.SessionMiddleware',

    # 7. 多语言（依赖 Session，必须在 SessionMiddleware 之后）
    'django.middleware.locale.LocaleMiddleware',

    # 8. 条件请求（ETag，必须在可能修改响应的中间件之前）
    'django.middleware.http.ConditionalGetMiddleware',

    # 9. 通用中间件（处理 APPEND_SLASH 等）
    'django.middleware.common.CommonMiddleware',

    # 10. CSRF 防护
    'django.middleware.csrf.CsrfViewMiddleware',

    # 11. 用户认证
    'django.contrib.auth.middleware.AuthenticationMiddleware',

    # 11.5 会话空闲超时（必须在认证之后；已登录用户超过阈值无操作则强制登出）
    'framework.security.idle_timeout.IdleTimeoutMiddleware',

    # 12. API 签名验证（在认证之后，业务逻辑之前拦截非法请求）
    'framework.api_signature.middleware.APISignatureMiddleware',

    # 13. SaaS 多租户上下文注入（必须在具体业务和日志记录之前）
    'system.saas.middleware.TenantMiddleware',

    # 14. API 网关（限流、请求日志）
    'framework.gateway.middleware.GatewayMiddleware',

    # 15. 操作日志（放在业务中间件之后，确保能捕获完整的上下文）
    'apps.system.core.middleware.OperationLogMiddleware',

    # 16. 消息框架
    'django.contrib.messages.middleware.MessageMiddleware',

    # 17. 点击劫持防护
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # 18. 全局指标采集结束
    'django_prometheus.middleware.PrometheusAfterMiddleware',

    # 19. 自定义业务指标（API 请求/延迟/错误率，排除内部路径）
    'framework.metrics.middleware.MetricsMiddleware',

    # 20. 滑动会话：将续期后的 access token 通过响应头返回前端
    'framework.drf.sliding_jwt.SlidingTokenMiddleware',
]

ROOT_URLCONF = 'djangoProjectTest.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'djangoProjectTest.wsgi.application'

# ASGI 配置（用于 WebSocket）
ASGI_APPLICATION = 'djangoProjectTest.asgi.application'

# Channels 配置
if global_config.redis.enabled:
    # 使用 Redis（生产环境推荐）
    redis_host = global_config.redis.host
    redis_port = global_config.redis.port
    redis_password = global_config.redis.password
    redis_db = global_config.redis.db
    
    # 构建 Redis 地址
    if redis_password:
        redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}"
    else:
        redis_url = f"redis://{redis_host}:{redis_port}/{redis_db}"
    
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [redis_url],
            },
        },
    }
else:
    # 使用内存（开发环境）
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'zh-hans'
LANGUAGES = [
    ('zh-hans', '简体中文'),
    ('en', 'English'),
]
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Token 有效期
TOKEN_EXPIRE_HOURS = global_config.TOKEN_EXPIRE_HOURS

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static_root')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = global_config.email.host
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = global_config.email.send_user
EMAIL_HOST_PASSWORD = global_config.email.stamp_key
DEFAULT_FROM_EMAIL = f"{global_config.project.name} <{global_config.email.send_user}>"

# REST Framework configuration
REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'framework.drf.exception_handler.global_exception_handler',
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'framework.drf.sliding_jwt.SlidingJWTAuthentication',  # JWT 认证（支持滑动续期）
        'framework.drf.api_key_auth.APIKeyAuthentication',  # API Key 认证（外部系统对接）
        'rest_framework.authentication.SessionAuthentication',  # Session 认证（浏览器页面使用）
        # 'rest_framework.authentication.BasicAuthentication',  # Basic 认证（已禁用）
        # 'system.users.authentication.ExpiringTokenAuthentication',  # Token 认证（已禁用）
    ],
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    'DEFAULT_PAGINATION_CLASS': 'djangoProjectTest.pagination.StandardPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': (
        'framework.drf.renderer.CustomRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'framework.gateway.throttle.IPThrottle',
        'framework.gateway.throttle.UserThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': '500/hour',
        'anon': '60/minute',
    },
    'DEFAULT_SCHEMA_CLASS': 'framework.drf.schema.PermissiveAutoSchema',
}

# JWT 配置
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=getattr(global_config, 'TOKEN_EXPIRE_HOURS', 24)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=getattr(global_config, 'REFRESH_TOKEN_EXPIRE_DAYS', 1)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': global_config.JWT_SIGNING_KEY or global_config.SECRET_KEY,  # 优先使用独立 JWT 密钥，未设置时回退到 SECRET_KEY
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
    
    'JTI_CLAIM': 'jti',
    
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(hours=24),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=7),
}

# =====================================================
# 生产环境异常处理脱敏
# 决定 400 字段校验错误(ValidationError)在生产是否脱敏：
#   False(默认) → 保留字段级 errors（前端表单提示需要，内容为静态校验文案、不含系统内部信息）
#   True        → 一并隐藏为通用消息「请求参数有误或处理失败」
# 注意：500 服务器内部错误在生产环境始终脱敏（绝不返回异常原文/类名/堆栈/内部路径），
#       仅写入日志，与此开关无关。
# =====================================================
PROD_MASK_VALIDATION_ERRORS = False

# =====================================================
# OIDC 单点登录（SSO）配置
# 仅在 global_config.oidc.enabled 为 True 时启用；未启用时不影响启动
# =====================================================
OIDC_ENABLED = getattr(global_config, 'OIDC_ENABLED', False)
if OIDC_ENABLED:
    OIDC_RP_CLIENT_ID = global_config.OIDC_RP_CLIENT_ID
    OIDC_RP_CLIENT_SECRET = global_config.OIDC_RP_CLIENT_SECRET
    OIDC_OP_AUTHORIZATION_ENDPOINT = global_config.OIDC_OP_AUTHORIZATION_ENDPOINT
    OIDC_OP_TOKEN_ENDPOINT = global_config.OIDC_OP_TOKEN_ENDPOINT
    OIDC_OP_USER_ENDPOINT = global_config.OIDC_OP_USER_ENDPOINT
    OIDC_OP_JWKS_ENDPOINT = global_config.OIDC_OP_JWKS_ENDPOINT
    OIDC_OP_LOGOUT_ENDPOINT = global_config.OIDC_OP_LOGOUT_ENDPOINT or None
    OIDC_RP_SIGN_ALGO = global_config.OIDC_RP_SIGN_ALGO
    OIDC_CREATE_USER = global_config.OIDC_CREATE_USER
    OIDC_USERNAME_CLAIM = global_config.OIDC_USERNAME_CLAIM
    # 防止回调重定向被滥用为开放重定向（需包含本应用 host）
    OIDC_REDIRECT_ALLOWED_HOSTS = list(ALLOWED_HOSTS)
    OIDC_FRONTEND_REDIRECT_URL = global_config.OIDC_FRONTEND_REDIRECT_URL
    OIDC_LOGOUT_REDIRECT_URL = global_config.OIDC_LOGOUT_REDIRECT_URL or '/'
    # 认证后端：保留账号密码(ModelBackend) + OIDC 自定义后端（双轨并存）
    AUTHENTICATION_BACKENDS = [
        'django.contrib.auth.backends.ModelBackend',
        'system.users.oidc.OIDCBackend',
    ]

# 滑动会话（Sliding Session）配置
SLIDING_SESSION_ENABLED = getattr(global_config, 'SLIDING_SESSION_ENABLED', False)
SLIDING_REFRESH_THRESHOLD_SECONDS = getattr(global_config, 'SLIDING_REFRESH_THRESHOLD_SECONDS', 300)

SPECTACULAR_SETTINGS = {
    'TITLE': f'{global_config.project.name} API Documentation',
    'DESCRIPTION': '企业级项目 API 接口文档',
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # 其他配置...
}

# =====================================================
# 企业级基础设施配置
# =====================================================

# --- Redis 缓存配置 ---
REDIS_CONFIG = global_config.redis.model_dump()

# 多级缓存配置
if REDIS_CONFIG.get('enabled', False):
    try:
        import django_redis
        _redis_host = REDIS_CONFIG["host"]
        _redis_port = REDIS_CONFIG["port"]
        _redis_db = REDIS_CONFIG["db"]
        _redis_password = REDIS_CONFIG.get("password")
        _redis_url = f'redis://{_redis_host}:{_redis_port}/{_redis_db}'
        if _redis_password:
            _redis_url = f'redis://:{_redis_password}@{_redis_host}:{_redis_port}/{_redis_db}'

        CACHES = {
            'default': {
                'BACKEND': 'django_redis.cache.RedisCache',
                'LOCATION': _redis_url,
                'OPTIONS': {
                    'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                    'PASSWORD': _redis_password,
                    'CONNECTION_POOL_KWARGS': {
                        'max_connections': REDIS_CONFIG['max_connections'],
                        'socket_timeout': REDIS_CONFIG['socket_timeout'],
                        'socket_connect_timeout': REDIS_CONFIG['socket_connect_timeout'],
                    },
                    'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
                    'SERIALIZER': 'django_redis.serializers.pickle.PickleSerializer',
                },
                'TIMEOUT': 60 * 30,  # 默认 30 分钟过期
                'KEY_PREFIX': 'cache',
                'KEY_FUNCTION': 'framework.cache.cache_manager.make_cache_key',
            },
        }
    except ImportError:
        # django-redis 未安装，回退到内存缓存
        CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'unique-snowflake',
                'TIMEOUT': 60 * 5,
            }
        }
else:
    # Redis 未启用，使用内存缓存
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
            'TIMEOUT': 60 * 5,
        }
    }

# =====================================================
# Session 配置（Redis 后端）
# =====================================================
if REDIS_CONFIG.get('enabled', False):
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
    SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 7 天
    SESSION_SAVE_EVERY_REQUEST = False

# 会话空闲超时（秒）：已登录用户超过该时长无任何操作则强制登出；0 表示禁用。
# 与 SESSION_COOKIE_AGE（绝对 7 天硬上限）互补：用户持续活跃可保活，一旦空闲超阈值立即踢出。
SESSION_IDLE_TIMEOUT_SECONDS = int(getattr(global_config, "SESSION_IDLE_TIMEOUT_SECONDS", 1800))

# 空闲超时排除路径前缀（不参与空闲计时的路径）；页面空闲超时后的重定向地址。
# 均来自 model.py 的 ProjectSettings，可经环境变量覆盖。
SESSION_IDLE_TIMEOUT_EXEMPT_PATHS = list(getattr(global_config, "SESSION_IDLE_TIMEOUT_EXEMPT_PATHS", []))
SESSION_IDLE_TIMEOUT_REDIRECT_URL = getattr(global_config, "SESSION_IDLE_TIMEOUT_REDIRECT_URL", "/admin/login/")

# =====================================================
# django-cachalot ORM 查询缓存配置
# =====================================================
CACHALOT_ENABLED = True
CACHALOT_TIMEOUT = 30  # ORM 缓存 30 秒（避免权限/角色变更长时间不生效）
CACHALOT_CACHE = 'default'
# 忽略高频写入表（Session、日志等）
CACHALOT_UNCACHABLE_TABLES = frozenset([
    'django_session',
    'django_migrations',
    'core_audit_log',
    'django_celery_beat_solarschedule',
    'django_celery_beat_clockedschedule',
])

LOGIN_URL = '/api/users/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# CORS configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Allow all in dev, restrict in prod

if not CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOWED_ORIGINS = global_config.CORS_ALLOWED_ORIGINS

# 暴露滑动续期响应头，使浏览器前端能读取到新的 access token
CORS_EXPOSE_HEADERS = ['X-Access-Token', 'X-Token-Refreshed']

# --- 项目业务配置 ---
PROJECT_NAME = global_config.project.name
TESTER_NAME = global_config.project.tester
ENV = global_config.project.env
NOTIFICATION_TYPE = global_config.notification.notification_type

# --- 通知系统配置 ---
DINGTALK_WEBHOOK = global_config.ding_talk.webhook
DINGTALK_SECRET = global_config.ding_talk.secret

FEISHU_WEBHOOK = global_config.feishu.webhook
FEISHU_SECRET = global_config.feishu.secret

LARK_WEBHOOK = global_config.lark.webhook

EMAIL_SEND_USER = global_config.email.send_user
EMAIL_HOST = global_config.email.host
EMAIL_STAMP_KEY = global_config.email.stamp_key
EMAIL_SEND_LIST = global_config.email.send_list

WECHAT_WEBHOOK = global_config.wechat.webhook

# --- 安全 HTTP 响应头配置 ---
# HTTPS 相关（生产环境务必启用）
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0  # 1 年
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
# X-Frame-Options: 防止点击劫持
X_FRAME_OPTIONS = 'DENY'
# Session Cookie 安全
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# --- 日志配置 ---
from framework.log_utils.loguru_control import LogManager, InterceptHandler
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
LogManager(log_dir=LOGS_DIR, level="DEBUG" if DEBUG else "INFO", debug=DEBUG)

# Django's own logging configuration - 所有日志都转发到 loguru
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'loguru': {
            'class': 'framework.log_utils.loguru_control.InterceptHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['loguru'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.server': {
            'handlers': ['loguru'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['loguru'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['loguru'],
            'level': 'WARNING',  # SQL 日志设为 WARNING 避免过多
            # 'level': 'DEBUG',
            'propagate': False,
        },
    }
}

# =====================================================
# API 网关限流配置
# =====================================================
GATEWAY_THROTTLE_RATES = {
    "ip":       "1000/h",    # 每 IP 每小时 1000 次
    "user":     "500/h",     # 每用户每小时 500 次
    "tenant":   "10000/h",   # 每租户每小时 10000 次
    "anon":     "60/m",      # 匿名用户每分钟 60 次
    "endpoint": "100/h",     # 每端点默认每小时 100 次
}

# =====================================================
# API Key 认证配置 (外部系统对接)
# =====================================================
# 简单模式：key → username 映射，无需数据库。
# 运行 `invoke secret.apikey` 生成新 Key。
# 生产模式：取消 apps/core/models.py 中 APIKey 模型的注释，
#           然后 makemigrations + migrate，通过 Django Admin 管理。
API_KEYS = {
    # "sk-xxxx-xxxx-xxxx": "admin",  # 示例: 将 Key 映射到 admin 用户
}

# =====================================================
# API 签名验证配置
# =====================================================
# 是否启用签名验证
API_SIGNATURE_ENABLED = True

# API 密钥（用于签名验证）— 生产环境必须通过环境变量 API_SECRET_KEY 设置
_api_secret_key = os.environ.get("API_SECRET_KEY", "")
if not _api_secret_key:
    if not DEBUG:
        raise RuntimeError(
            "API_SECRET_KEY 环境变量未设置。生产环境必须配置独立的 API 签名密钥。"
            "请在 .env 文件中设置 API_SECRET_KEY=<your-secure-random-key>"
        )
    _api_secret_key = "dev-only-secret-key-not-for-production"
API_SECRET_KEY = _api_secret_key

# 多租户 access_key 配置（可选）
API_ACCESS_KEYS = {
    # "access_key_1": "secret_key_1",
    # "access_key_2": "secret_key_2",
}

# 需要验证签名的路径（支持通配符）
API_SIGNATURE_PATHS = [
    "/api/*",
    "/api/v1/*",
]

# 排除签名验证的路径
# 任何公开的 /api 接口,都必须在这儿加上，不然前端调取不到
API_SIGNATURE_EXCLUDE_PATHS = [
    "/api/users/login/",
    "/api/users/register/",
    "/api/jwt/login/",
    "/api/jwt/refresh/",
    "/api/jwt/verify/",
    "/api/docs/",
    "/api/health/",
    "/api/health/*",
    "/api/ping/",
    # 第一方 Web SPA（带 JWT 的浏览器客户端）走 JWT 鉴权，不做签名校验
    "/api/ai_studio/*",
    "/api/ai_gateway/*",
]

# 时间戳容忍度（秒）
API_TIMESTAMP_TOLERANCE = 300  # 5分钟

# Nonce 有效期（秒）
API_NONCE_TTL = 600  # 10分钟

# =====================================================
# Celery 配置
# =====================================================
CELERY_BROKER_URL = None
CELERY_RESULT_BACKEND = None

if REDIS_CONFIG.get('enabled', False):
    # 使用 Redis 作为 Celery 后端
    redis_host = REDIS_CONFIG.get('host', 'localhost')
    redis_port = REDIS_CONFIG.get('port', 6379)
    redis_db = REDIS_CONFIG.get('db', 1)
    redis_password = REDIS_CONFIG.get('password')

    if redis_password:
        CELERY_BROKER_URL = f'redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}'
        CELERY_RESULT_BACKEND = f'redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}'
    else:
        CELERY_BROKER_URL = f'redis://{redis_host}:{redis_port}/{redis_db}'
        CELERY_RESULT_BACKEND = f'redis://{redis_host}:{redis_port}/{redis_db}'

# 允许通过环境变量显式覆盖 broker（例如跨服务连 RabbitMQ：amqp://host:5672//）
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", CELERY_BROKER_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_RESULT_BACKEND)

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Shanghai'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# 允许通过环境变量覆盖 broker / result backend（跨服务接入 RabbitMQ 等 MQ）
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or CELERY_BROKER_URL
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or CELERY_RESULT_BACKEND

# =====================================================
# Flower 监控配置
# =====================================================
# Flower Web UI 端口
FLOWER_PORT = int(os.environ.get("FLOWER_PORT", "5555"))
# Flower URL 前缀（用于反向代理）
FLOWER_URL_PREFIX = os.environ.get("FLOWER_URL_PREFIX", "flower")
# Flower 基础认证 (用户名:密码)
FLOWER_BASIC_AUTH = os.environ.get("FLOWER_BASIC_AUTH", "")
# Flower 最大任务数（保留在内存中的历史任务）
FLOWER_MAX_TASKS = int(os.environ.get("FLOWER_MAX_TASKS", "1000"))
# Flower 自动刷新间隔（秒）
FLOWER_REFRESH_TIME = int(os.environ.get("FLOWER_REFRESH_TIME", "5"))

# =====================================================
# DB 连接池配置
# =====================================================
# 在 settings.DATABASES['default']['_pool']（顶层键，Django 不会透传给驱动）
# 中可覆盖：
#   "_pool": {
#     "enabled": True,
#     "min_size": 2,
#     "max_size": 10,
#     "timeout": 30,
#     "max_idle": 600,
#     "max_lifetime": 3600,
#     "pre_ping": True
#   }
# ⚠️ 千万不要放进 OPTIONS['pool']，否则 OPTIONS 整盘 **conn_params
#    展开后会把 pool 传给驱动 connect()，触发 TypeError。
# 仅对 PostgreSQL / MySQL 生效；SQLite 自动走 CONN_MAX_AGE 长连接。
DB_POOL_DEFAULT_OPTIONS = {
    "enabled":   os.environ.get("DB_POOL_ENABLED", "true" if not DEBUG else "false").lower() == "true",
    "min_size":  int(os.environ.get("DB_POOL_MIN_SIZE", "2")),
    "max_size":  int(os.environ.get("DB_POOL_MAX_SIZE", "20")),
    "timeout":   float(os.environ.get("DB_POOL_TIMEOUT", "30")),
    "max_idle":  float(os.environ.get("DB_POOL_MAX_IDLE", "600")),
    "max_lifetime": float(os.environ.get("DB_POOL_MAX_LIFETIME", "3600")),
    "pre_ping":  os.environ.get("DB_POOL_PRE_PING", "true").lower() == "true",
}

# =====================================================
# Whitenoise 静态文件配置
# =====================================================
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# =====================================================
# 文件上传配置
# =====================================================
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

# 文件验证配置
FILE_UPLOAD_ALLOWED_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
}
FILE_UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_ENABLE_VIRUS_SCAN = False

# 图片处理配置
IMAGE_PROCESSING_MAX_WIDTH = 1920
IMAGE_PROCESSING_MAX_HEIGHT = 1080
IMAGE_PROCESSING_QUALITY = 85
IMAGE_PROCESSING_KEEP_EXIF = False

# 临时文件清理配置
FILE_UPLOAD_TEMP_DIRS = [
    '/tmp',
    os.path.join(str(MEDIA_ROOT), 'temp'),
]
FILE_UPLOAD_DIRS = [
    str(MEDIA_ROOT),
]
TEMP_FILE_MAX_AGE_HOURS = 24  # 临时文件保留 24 小时
OLD_UPLOAD_MAX_AGE_DAYS = 30  # 旧上传文件保留 30 天

# =====================================================
# Sentry 错误追踪配置
# =====================================================
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

if SENTRY_DSN and not DEBUG:
    try:
        from framework.core.sentry_init import init_sentry
        init_sentry()
    except ImportError:
        pass

# =====================================================
# Prometheus 指标监控配置
# =====================================================
PROMETHEUS_METRIC_NAMESPACE = "django"

# ================================================================
# 监控 / 可观测性补充配置
# ================================================================

# 主动探活任务（core.tasks.probe_dependencies）在依赖组件失败时，
# 经 alert_system.AlertEngine 发送的渠道。为空列表时仅记录告警历史、不外发。
# 可用渠道需与通知系统支持的一致，例如: ["dingtalk", "feishu", "email"]
ALERT_PROBE_CHANNELS = []

# 指标中间件排除统计的路径前缀（避免 /metrics 自监控、健康检查、静态资源等噪声）
METRICS_EXCLUDE_PATHS = (
    "/metrics",
    "/api/health",
    "/static",
    "/static_root",
    "/media",
    "/admin",
    "/favicon.ico",
)

# ----------------------------------------------------------------
# P2 监控增强配置（ERROR 突增 / 慢查询 / 长事务 / 安全扫描 / 健康日报）
# ----------------------------------------------------------------

# 1) ERROR 日志突增（core.tasks.check_error_spike，每 5 分钟）
ALERT_ERROR_SPIKE_THRESHOLD = int(os.environ.get("ALERT_ERROR_SPIKE_THRESHOLD", "50"))  # 窗口内 ERROR 条数阈值
ALERT_ERROR_SPIKE_WINDOW = int(os.environ.get("ALERT_ERROR_SPIKE_WINDOW", "300"))       # 滑动窗口秒数（与 beat 周期对应）
ALERT_ERROR_SPIKE_COOLDOWN = int(os.environ.get("ALERT_ERROR_SPIKE_COOLDOWN", "3600"))  # 同一进程两次告警最小间隔（秒）
ALERT_ERROR_SPIKE_CHANNELS = []  # 外发渠道，空=仅记录历史

# 2) 慢查询监控（framework.db.monitoring，全局计时）
DB_SLOW_QUERY_THRESHOLD = float(os.environ.get("DB_SLOW_QUERY_THRESHOLD", "1.0"))  # 慢查询阈值（秒）
DB_SLOW_QUERY_ALERT = os.environ.get("DB_SLOW_QUERY_ALERT", "True").lower() in ("1", "true", "yes")
DB_SLOW_QUERY_ALERT_COOLDOWN = int(os.environ.get("DB_SLOW_QUERY_ALERT_COOLDOWN", "3600"))

# 3) 长事务监控（core.tasks.check_long_transactions，需 PostgreSQL）
DB_LONG_TX_ALIAS = os.environ.get("DB_LONG_TX_ALIAS", "default")
DB_LONG_TX_THRESHOLD = int(os.environ.get("DB_LONG_TX_THRESHOLD", "30"))  # 事务打开超过该秒数视为长事务

# 4) 安全扫描（key_management.security_audit，每日）
TLS_CERT_PATHS = []  # 证书文件或目录列表，如 ["/etc/nginx/certs", "/path/to/server.pem"]
TLS_CERT_WARN_DAYS = int(os.environ.get("TLS_CERT_WARN_DAYS", "30"))  # 剩余天数低于此值告警
SECRET_LEAK_SCAN_PATHS = []  # 为空时默认扫描 apps/framework/extensions
KEY_MAX_AGE_DAYS = int(os.environ.get("KEY_MAX_AGE_DAYS", "90"))  # 主密钥最大年龄（天）
ALERT_SECURITY_CHANNELS = []  # 安全类告警外发渠道

# 5) 每日健康日报（core.tasks.daily_health_report，每日 09:00）
#    仅当对应 webhook 已配置且开关为 True 时才推送
DAILY_REPORT_DINGTALK = os.environ.get("DAILY_REPORT_DINGTALK", "True").lower() in ("1", "true", "yes")
DAILY_REPORT_FEISHU = os.environ.get("DAILY_REPORT_FEISHU", "True").lower() in ("1", "true", "yes")

