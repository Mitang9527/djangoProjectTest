# =============================================================================
# Django 企业级项目 - 基础配置 (base.py)
# -----------------------------------------------------------------------------
# 各环境共用基础配置；环境差异通过 global_config (Pydantic 校验) 与 .env 注入。
# 组织顺序：核心 → 应用 → 中间件 → 路由/模板 → 数据库/缓存/会话 →
#           认证/JWT/OIDC → API 网关/签名 → 文件上传/存储 → 通知/邮件 →
#           安全头 → 国际化 → 日志 → 文档 → Celery → 监控可观测性 → 其他基础设施
# =============================================================================

# ----------------------------------------------------------------------------
# 0. 导入 / 路径
# ----------------------------------------------------------------------------
import os
import sys
import re
from datetime import timedelta
from pathlib import Path
from ..model import global_config
from framework.log_utils.loguru_control import LogManager, InterceptHandler

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Add apps & extensions directories to sys.path (both are import roots)
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))
sys.path.insert(0, os.path.join(BASE_DIR, 'extensions'))

# ----------------------------------------------------------------------------
# 1. 核心配置 (Core)
# ----------------------------------------------------------------------------
# 调试模式（生产环境必须设为 False）
DEBUG = global_config.DEBUG

# 密钥（生产环境必须修改！可用 python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())" 生成）
SECRET_KEY = global_config.SECRET_KEY

# 演示登录开关（默认关闭，避免生产环境无认证即可签发 JWT；开发时设 ALLOW_DEMO_LOGIN=True）
ALLOW_DEMO_LOGIN = os.environ.get("ALLOW_DEMO_LOGIN", "False").strip().lower() in ("1", "true", "yes", "on")

# 允许的主机名（生产环境必须配置实际域名）
ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# Access Token 有效期（小时）
TOKEN_EXPIRE_HOURS = global_config.TOKEN_EXPIRE_HOURS

# ----------------------------------------------------------------------------
# 2. 应用注册 (INSTALLED_APPS)
# ----------------------------------------------------------------------------
# Django 自带应用
SHARED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

# 第三方库 app
THIRD_PARTY_APPS = [
    'rest_framework',                       # 开发 REST API
    # 'rest_framework.authtoken',           # Token 认证（已弃用）
    'rest_framework_simplejwt',            # JWT 认证
    'rest_framework_simplejwt.token_blacklist',  # JWT 黑名单
    'channels',                            # WebSocket 支持
    'django_filters',                      # 接口过滤
    'corsheaders',                         # 解决前后端跨域
    'drf_spectacular',                     # Swagger 文档生成
    'django_extensions',                   # Django 扩展工具
    'django_celery_beat',                  # Celery 定时任务
    'cachalot',                            # ORM 查询自动缓存
    'django_prometheus',                   # Prometheus 指标监控
    'mozilla_django_oidc',                 # OIDC 单点登录（SSO）
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

# 自定义用户模型
AUTH_USER_MODEL = 'users.User'

INSTALLED_APPS = SHARED_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ----------------------------------------------------------------------------
# 3. 中间件 (Middleware)
# ----------------------------------------------------------------------------
MIDDLEWARE = [
    # 1. 全局指标采集（必须成对出现，且包裹所有逻辑）
    'django_prometheus.middleware.PrometheusBeforeMiddleware',

    # 2. 链路追踪（尽早生成 Request-ID，供后续所有中间件和日志使用）
    'framework.log_utils.request_id.RequestIDMiddleware',

    # 3. 安全与重定向（最外层的安全防护）
    'django.middleware.security.SecurityMiddleware',

    # 3.5 CSP 响应头（缓解 XSS / 点击劫持；DEBUG 下关闭以免干扰 DRF Browsable API）
    'framework.security.csp.CSPMiddleware',

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

    # 12.5 Authorization 头自动补全 Bearer 前缀（手动测试裸 token 免手敲 Bearer；
    #      已带 Bearer/Basic 等方案的头不受影响，X-API-Key 独立头不受影响）
    'framework.drf.auth_normalize.AuthorizationBearerMiddleware',

    # 13. SaaS 多租户上下文注入（必须在具体业务和日志记录之前）
    'system.saas.middleware.TenantMiddleware',

    # 14. API 网关（限流、请求日志）
    'framework.gateway.middleware.GatewayMiddleware',

    # 15. 操作日志（放在业务中间件之后，确保能捕获完整的上下文）
    'system.core.middleware.OperationLogMiddleware',

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

# ----------------------------------------------------------------------------
# 4. 路由 / 模板 / WSGI / ASGI
# ----------------------------------------------------------------------------
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

# Channels 配置（生产环境推荐 Redis，开发环境回退内存）
if global_config.redis.enabled:
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

# ----------------------------------------------------------------------------
# 5. 数据库 / 缓存 / 会话
# ----------------------------------------------------------------------------
# 数据库读写分离（主从）路由：默认不启用；各环境在 DATABASES 定义后调用
# apply_replica() 注入副本与路由。未配置 DB_REPLICA_URL / DB_REPLICA_DSN 时保持单
# 库，零风险。apply_replica 是对 framework.db.replica.install_replica 的薄封装，
# 避免 dev/prod/test 三处重复 import 同一模块。
DATABASE_ROUTERS = []


def apply_replica(databases, routers):
    """注入读写分离副本库与路由（仅当配置了 DB_REPLICA_URL / DB_REPLICA_DSN）。

    封装 framework.db.replica.install_replica，供各环境在定义完 DATABASES 后调用，
    避免在 dev/prod/test 三处重复 import 同一模块。
    """
    from framework.db.replica import install_replica  # 延迟导入，避免影响 settings 首次加载
    return install_replica(databases, routers)

# Redis 配置（缓存 + WebSocket Channel Layer）
REDIS_CONFIG = global_config.redis.model_dump()

# 多级缓存配置（Redis 启用且 django-redis 可用时走 Redis，否则回退内存缓存）
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

# Session 配置（Redis 后端）
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

# django-cachalot ORM 查询缓存配置
CACHALOT_ENABLED = True
CACHALOT_TIMEOUT = 30  # ORM 缓存 30 秒（避免权限/角色变更长时间不生效）
CACHALOT_CACHE = 'default'
# 迁移期间 cachalot 会缓存 django_content_type 查询并返回陈旧的空结果，
# 导致 create_contenttypes 重复插入 -> UNIQUE constraint failed。
# 仅在执行 migrate 命令时关闭查询缓存（不影响运行时缓存）。
import sys as _sys
if 'migrate' in _sys.argv:
    CACHALOT_ENABLED = False
# 忽略高频写入表（Session、日志等）
CACHALOT_UNCACHABLE_TABLES = frozenset([
    'django_session',
    'django_migrations',
    'core_audit_log',
    'django_celery_beat_solarschedule',
    'django_celery_beat_clockedschedule',
])

# ----------------------------------------------------------------------------
# 6. 认证 / JWT / OIDC
# ----------------------------------------------------------------------------
# 登录相关 URL（浏览器页面使用；API 客户端走 /api/v1/users/login/）
LOGIN_URL = '/api/users/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# 密码强度校验
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

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
    # 注意：版本控制统一由 URL 路径前缀（/api/v1/、/api/v2/…）实现，由 settings.API_VERSIONS
    # 驱动；不启用 DRF AcceptHeader 版本化，避免「路径 + header」双机制并存导致路由与文档混乱。
}

# JWT 配置
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=getattr(global_config, 'TOKEN_EXPIRE_HOURS', 24)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=getattr(global_config, 'REFRESH_TOKEN_EXPIRE_DAYS', 1)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': global_config.JWT_SIGNING_KEY or (global_config.SECRET_KEY if DEBUG else None),  # 独立 JWT 密钥；未设置时仅 DEBUG 回退到 SECRET_KEY
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

# 安全护栏：生产环境强制使用独立的 JWT_SIGNING_KEY，禁止回退到 SECRET_KEY
# （SECRET_KEY 一旦泄露即可伪造任意 JWT；主平台与 AI 服务须配置为相同值以实现跨服务验签）
if not SIMPLE_JWT.get('SIGNING_KEY'):
    raise RuntimeError(
        "JWT_SIGNING_KEY 环境变量未设置。生产环境必须使用独立的 JWT 签名密钥，"
        "且主平台与 AI 服务须配置为相同值；请勿回退到 SECRET_KEY。"
    )

# OIDC 单点登录（SSO）配置
# 仅在 global_config.oidc.enabled 为 True 时启用；未启用时不影响启动
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

# ----------------------------------------------------------------------------
# 7. API 网关 / 签名 / 版本 / 限流
# ----------------------------------------------------------------------------
# CORS 跨域配置
# 开发环境允许所有来源；生产环境按 global_config.CORS_ALLOWED_ORIGINS 限制。
CORS_ALLOW_ALL_ORIGINS = DEBUG

if not CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOWED_ORIGINS = global_config.CORS_ALLOWED_ORIGINS

# 暴露滑动续期响应头，使浏览器前端能读取到新的 access token
CORS_EXPOSE_HEADERS = ['X-Access-Token', 'X-Token-Refreshed']

# API 网关限流配置
GATEWAY_THROTTLE_RATES = {
    "ip":       "1000/h",    # 每 IP 每小时 1000 次
    "user":     "500/h",     # 每用户每小时 500 次
    "tenant":   "10000/h",   # 每租户每小时 10000 次
    "anon":     "60/m",      # 匿名用户每分钟 60 次
    "endpoint": "100/h",     # 每端点默认每小时 100 次
}

# API Key 认证配置 (外部系统对接)
# 简单模式：key → username 映射，无需数据库。运行 `invoke secret.apikey` 生成新 Key。
# 生产模式：取消 apps/core/models.py 中 APIKey 模型的注释，然后 makemigrations + migrate，通过 Django Admin 管理。
API_KEYS = {
    # "sk-xxxx-xxxx-xxxx": "admin",  # 示例: 将 Key 映射到 admin 用户
}

# API 签名验证配置
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

# 业务 API 版本列表（URL 路径版本化的权威来源）
# - 驱动自动发现路由挂载 /api/<version>/<leaf>/
# - 驱动主 urls 是否挂载 /api/v2/users/ 等手动 v2 路由
# - 新增版本：此处追加（如 'v2'）并确保对应 app 提供 <version>_urls 模块
API_VERSIONS = ['v1']

# 排除签名验证的路径
# 任何公开的 /api 接口,都必须在这儿加上，不然前端调取不到
API_SIGNATURE_EXCLUDE_PATHS = [
    # ---- 用户认证（浏览器/SPA，JWT 鉴权，不做请求签名）----
    "/api/v1/users/*",

    # ---- SaaS 后台（浏览器/SPA，JWT 鉴权，不做请求签名）----
    "/api/v1/saas/*",

    # ---- 核心平台公开/监控/外部鉴权端点 ----
    # 核心平台已收口到 /api/v1/core/，其监控/外部端点落入 /api/* 签名拦截，
    # 需在此显式放行（探活/依赖检查/前端调用均不带签名头）。

    "/api/v1/core/ping/",
    "/api/v1/core/ping-auth/",
    "/api/v1/core/secure-info/",
    "/api/v1/core/demo-login/",
    "/api/v1/core/api-keys/*",
    "/api/v1/core/upload/file/",
    "/api/v1/core/upload/image/",
    "/api/v1/core/upload/video/",
    "/api/v1/core/upload/audio/",
    "/api/v1/core/health/",
    "/api/v1/core/health/*",
    "/api/v1/core/system-status/",
    "/api/v1/core/token/info/",

    # ---- 第一方 Web SPA（带 JWT 的浏览器客户端）走 JWT 鉴权，不做签名校验 ----
    "/api/v1/ai_studio/*",
    "/api/v1/ai_gateway/*",
    # ---- 业务服务 ----
    "/api/v1/alert_system/*",
]

# 时间戳容忍度（秒）
API_TIMESTAMP_TOLERANCE = 300  # 5分钟

# Nonce 有效期（秒）
API_NONCE_TTL = 600  # 10分钟

# 生产环境异常处理脱敏
# 决定 400 字段校验错误(ValidationError)在生产是否脱敏：
#   False(默认) → 保留字段级 errors（前端表单提示需要，内容为静态校验文案、不含系统内部信息）
#   True        → 一并隐藏为通用消息「请求参数有误或处理失败」
# 注意：500 服务器内部错误在生产环境始终脱敏（绝不返回异常原文/类名/堆栈/内部路径），
#       仅写入日志，与此开关无关。
PROD_MASK_VALIDATION_ERRORS = False

# ----------------------------------------------------------------------------
# 8. 文件上传 / 媒体 / 存储 (OSS)
# ----------------------------------------------------------------------------
# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static_root')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# 对象存储 (OSS) 配置 —— framework.storage
# 与 Redis 接入方式一致：从 global_config.oss 读取校验后的配置。
# backend: local(默认) | aliyun | s3(minio/cos/obs 等兼容)
# 未启用 / SDK 缺失时自动降级为本地磁盘 (MEDIA_ROOT/oss)，业务不中断。
OSS_CONFIG = global_config.oss.model_dump()
STORAGE_BACKEND = os.environ.get("OSS_BACKEND", OSS_CONFIG.get("backend", "local"))

# DEFAULT_FILE_STORAGE：如需让 Django 模型 FileField 默认落到 OSS，可设为：
#   "framework.storage.django_storage.DjangoOSSStorage"
# 默认为本地文件系统（与 Django 原生一致）。
DEFAULT_FILE_STORAGE = os.environ.get(
    "DJANGO_DEFAULT_FILE_STORAGE",
    "django.core.files.storage.FileSystemStorage",
)

# 文件上传通用配置
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755
# 文件验证配置
# 当前 validator 使用 framework.files.upload.validators.FileValidator 内置的
# DEFAULT_ALLOWED_TYPES / DEFAULT_ALLOWED_EXTENSIONS 作为权威白名单，本变量为同义冗余配置，
# 保留以便后续若改为「settings 驱动白名单」时直接启用。
FILE_UPLOAD_ALLOWED_TYPES = {
    # 图片
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'image/bmp', 'image/x-icon', 'image/tiff',
    'image/heic', 'image/heif', 'image/avif',
    # 视频
    'video/mp4', 'video/webm', 'video/quicktime', 'video/avi',
    'video/x-matroska', 'video/x-flv', 'video/x-ms-wmv', 'video/x-m4v',
    'video/ogg', 'video/mpeg', 'video/3gpp', 'video/mp2t',
    'video/vnd.dlna.mpeg-tts',
    # 音频
    'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/vnd.dlna.adts',
    'audio/x-flac', 'audio/mp4',
    'audio/opus', 'audio/midi',
    'audio/mid',
    # 文档 / 数据 / 归档 / 字体
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain', 'text/csv', 'text/markdown', 'text/xml',
    'application/json',
    'application/x-zip-compressed',
    'application/vnd.oasis.opendocument.text',
    'application/vnd.oasis.opendocument.spreadsheet',
    'application/vnd.oasis.opendocument.presentation',
    'application/epub+zip', 'application/epub',
    'text/calendar', 'text/vcard', 'text/x-vcard',
    'text/tab-separated-values',
    'application/yaml', 'text/yaml', 'application/x-yaml',
    'application/x-7z-compressed', 'application/x-tar',
    'application/gzip', 'application/x-gzip',
    'application/vnd.rar', 'application/x-rar-compressed',
    'application/x-compressed',
    'font/woff', 'application/font-woff', 'application/x-font-woff',
    'font/woff2', 'application/font-woff2', 'application/x-font-woff2',
    'font/ttf', 'application/x-font-ttf',
    'font/otf', 'application/x-font-otf',
}
# 单文件通用上限（非视频）
FILE_UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
# 视频类单独放宽上限（容器天然更大，避免被通用 10MB 误伤）。
# 该值须与 framework 层 validator 的 DEFAULT_MAX_VIDEO_FILE_SIZE 对齐；
# 同时 DATA_UPLOAD_MAX_MEMORY_SIZE 必须 >= 此值 + multipart 开销，否则大视频在解析阶段被拒。
FILE_UPLOAD_MAX_VIDEO_FILE_SIZE = 100 * 1024 * 1024  # 100MB
# 框架层上传 DoS 防护：请求体超过该值（含所有字段与文件）直接在解析阶段拒绝，
# 防止恶意用户疯狂上传大文件耗尽内存/磁盘。必须 >= 视频单文件上限（100MB）+ multipart 开销，
# 否则正常大视频会在解析阶段被 413 拒绝；放宽视频可用性后，DoS 防护由 per-file 上限 + 鉴权兜底。
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024 + 10 * 1024 * 1024  # 110MB（>= 视频上限 + 开销）
# 超过该值的部分流式写入临时文件（而非常驻内存），降低内存压力。
# 注意：此值须 < DATA_UPLOAD_MAX_MEMORY_SIZE，否则大文件会在 multipart 解析阶段被 413 拒绝。
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB
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

# ----------------------------------------------------------------------------
# 9. 通知 / 邮件
# ----------------------------------------------------------------------------
# 项目基础信息
PROJECT_NAME = global_config.project.name
TESTER_NAME = global_config.project.tester
ENV = global_config.project.env
NOTIFICATION_TYPE = global_config.notification.notification_type

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = global_config.email.host
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = global_config.email.send_user
EMAIL_HOST_PASSWORD = global_config.email.stamp_key
DEFAULT_FROM_EMAIL = f"{global_config.project.name} <{global_config.email.send_user}>"
EMAIL_SEND_USER = global_config.email.send_user
EMAIL_STAMP_KEY = global_config.email.stamp_key
EMAIL_SEND_LIST = global_config.email.send_list

# 钉钉
DINGTALK_WEBHOOK = global_config.ding_talk.webhook
DINGTALK_SECRET = global_config.ding_talk.secret

# 飞书
FEISHU_WEBHOOK = global_config.feishu.webhook
FEISHU_SECRET = global_config.feishu.secret

# Lark
LARK_WEBHOOK = global_config.lark.webhook

# 企业微信
WECHAT_WEBHOOK = global_config.wechat.webhook

# ----------------------------------------------------------------------------
# 10. 安全 HTTP 响应头
# ----------------------------------------------------------------------------
# HTTPS 相关（生产环境务必启用）
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0  # 1 年
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
# CSP 响应头：生产环境开启；DEBUG 下关闭，避免干扰 DRF Browsable API 的内联脚本
CSP_ENABLED = not DEBUG
# X-Frame-Options: 防止点击劫持
X_FRAME_OPTIONS = 'DENY'
# Session Cookie 安全
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'

# ----------------------------------------------------------------------------
# 11. 国际化
# ----------------------------------------------------------------------------
LANGUAGE_CODE = 'zh-hans'
LANGUAGES = [
    ('zh-hans', '简体中文'),
    ('en', 'English'),
]
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ----------------------------------------------------------------------------
# 12. 日志 (Loguru)
# ----------------------------------------------------------------------------
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
# 日志级别可由 LOG_LEVEL 环境变量覆盖（DEBUG/INFO/WARNING/ERROR），默认 DEBUG 时 DEBUG、否则 INFO
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()
LogManager(log_dir=LOGS_DIR, level=LOG_LEVEL, debug=DEBUG)

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
            'level': LOG_LEVEL,
            'propagate': True,
        },
        'django.server': {
            'handlers': ['loguru'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'django.request': {
            'handlers': ['loguru'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['loguru'],
            'level': 'WARNING',  # SQL 日志设为 WARNING 避免过多
            # 'level': 'DEBUG',
            'propagate': False,
        },
        'django.template': {
            # 模板引擎在 DEBUG 下每次变量解析失败都打 DEBUG 刷屏；
            # 本项目是纯 API 后端（零模板），这些 DEBUG 完全是噪音。
            'handlers': ['loguru'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.utils.autoreload': {
            # 开发模式 runserver 的 autoreload 会每 tick 打 DEBUG（扫描文件 mtime）刷屏；
            'handlers': [],
            'level': 'INFO',
            'propagate': False,
        },
    }
}

# ----------------------------------------------------------------------------
# 13. API 文档 (Swagger / OpenAPI)
# ----------------------------------------------------------------------------
# 业务应用 Swagger 分组（顺序即展示顺序；未列出的应用自动追加到末尾）
_API_TAG_DESCRIPTIONS = {
    'users': '用户认证与账号管理（登录/JWT/注册/资料）',
    'core': '系统核心能力（健康检查/API Key/系统配置）',
    'saas': '多租户 SaaS 管理（租户/套餐/额度）',
    'ai_studio': 'AI 创作服务（生成任务/结果拉取）',
    'alert_system': '告警与通知系统（规则/历史/通知配置）',
    'soul': 'Soul 业务模块',
    'apk_tool': 'APK 工具（扩展）',
    'adb_web': 'ADB Web 调试（扩展）',
    'web_automation': 'Web 自动化（扩展）',
}

SPECTACULAR_SETTINGS = {
    'TITLE': f'{global_config.project.name} API Documentation',
    'DESCRIPTION': '企业级项目 API 接口文档',
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # --- Swagger UI 增强 ---
    'SWAGGER_UI_SETTINGS': {
        'persistAuthorization': True,       # 刷新/复制链接后保留 JWT
        'docExpansion': 'none',             # 默认折叠全部接口
        'filter': True,                     # 顶部接口搜索框
        'displayRequestDuration': True,     # 显示请求耗时
        'tryItOutEnabled': True,            # 默认展开 Try it out
    },
    # --- 认证方式：全局 Bearer JWT（Authorize 按钮） ---
    'SECURITY': [{'BearerAuth': []}],
    'SECURITY_SCHEMES': {
        'BearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'},
    },
    'COMPONENT_SPLIT_REQUEST': True,        # 请求体拆分 JSON / multipart 两类
    'TAGS': [
        {'name': name, 'description': desc}
        for name, desc in _API_TAG_DESCRIPTIONS.items()
    ],
}

# ----------------------------------------------------------------------------
# 14. Celery / Flower
# ----------------------------------------------------------------------------
# broker / result backend 优先级：环境变量 > Redis（若启用）> None
# 例如跨服务连 RabbitMQ 时可设 CELERY_BROKER_URL=amqp://host:5672//
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND")

if REDIS_CONFIG.get('enabled', False):
    # 使用 Redis 作为 Celery 后端（仅在未通过环境变量指定时生效）
    redis_host = REDIS_CONFIG.get('host', 'localhost')
    redis_port = REDIS_CONFIG.get('port', 6379)
    redis_db = REDIS_CONFIG.get('db', 1)
    redis_password = REDIS_CONFIG.get('password')
    if redis_password:
        redis_url = f'redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}'
    else:
        redis_url = f'redis://{redis_host}:{redis_port}/{redis_db}'
    CELERY_BROKER_URL = CELERY_BROKER_URL or redis_url
    CELERY_RESULT_BACKEND = CELERY_RESULT_BACKEND or redis_url

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Shanghai'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Flower 监控配置
FLOWER_PORT = int(os.environ.get("FLOWER_PORT", "5555"))                              # Web UI 端口
FLOWER_URL_PREFIX = os.environ.get("FLOWER_URL_PREFIX", "flower")                    # URL 前缀（反向代理用）
FLOWER_BASIC_AUTH = os.environ.get("FLOWER_BASIC_AUTH", "")                          # 基础认证 (用户名:密码)
FLOWER_MAX_TASKS = int(os.environ.get("FLOWER_MAX_TASKS", "1000"))                   # 内存保留历史任务数
FLOWER_REFRESH_TIME = int(os.environ.get("FLOWER_REFRESH_TIME", "5"))                # 自动刷新间隔（秒）

# ----------------------------------------------------------------------------
# 15. 监控 / 可观测性 (Prometheus / Sentry / 告警)
# ----------------------------------------------------------------------------
# Prometheus 指标监控配置
PROMETHEUS_METRIC_NAMESPACE = "django"

# Sentry 错误追踪配置
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN and not DEBUG:
    try:
        from framework.core.sentry_init import init_sentry
        init_sentry()
    except Exception:  # Sentry 任何异常都不应阻断启动（init_sentry 内部已记录）
        pass

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

# P2 监控增强配置（ERROR 突增 / 慢查询 / 长事务 / 安全扫描 / 健康日报）

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

# ----------------------------------------------------------------------------
# 16. 其他基础设施 (DB Pool / Whitenoise)
# ----------------------------------------------------------------------------
# DB 连接池配置
# 在 settings.DATABASES['default']['_pool']（顶层键，Django 不会透传给驱动）中可覆盖：
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

# Whitenoise 静态文件配置
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
