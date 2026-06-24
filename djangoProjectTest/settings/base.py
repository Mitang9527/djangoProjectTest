import os
import sys
import re
from pathlib import Path
from ..model import global_config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Add apps directory to sys.path
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))

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

# --- 自动发现 LOCAL_APPS ---
def discover_local_apps(apps_dir):
    local_apps = []
    if not os.path.exists(apps_dir):
        return local_apps
    
    for item in os.listdir(apps_dir):
        item_path = os.path.join(apps_dir, item)
        apps_file = os.path.join(item_path, 'apps.py')
        
        # 判断是否为 app：目录且包含 apps.py
        if os.path.isdir(item_path) and os.path.exists(apps_file):
            try:
                with open(apps_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 使用正则匹配继承自 AppConfig 的类名
                    match = re.search(r'class\s+(\w+)\(AppConfig\):', content)
                    if match:
                        config_class = match.group(1)
                        local_apps.append(f"{item}.apps.{config_class}")
                    else:
                        # 备选方案：如果正则没匹配到，尝试传统的首字母大写
                        config_class = f"{item.capitalize()}Config"
                        local_apps.append(f"{item}.apps.{config_class}")
            except Exception:
                # 容错处理
                config_class = f"{item.capitalize()}Config"
                local_apps.append(f"{item}.apps.{config_class}")
    return local_apps

LOCAL_APPS = discover_local_apps(os.path.join(BASE_DIR, 'apps'))

# 第三方库 app
THIRD_PARTY_APPS = [
    'rest_framework',   # 开发 REST API
    # 'rest_framework.authtoken',     # Token 认证（已禁用）
    'rest_framework_simplejwt',     # JWT 认证
    'rest_framework_simplejwt.token_blacklist',  # JWT 黑名单
    'channels',  # WebSocket 支持
    'django_filters',   #接口过滤
    'corsheaders',     #解决前后端跨域
    'bootstrap4',    #前端 CSS 框架
    'drf_spectacular',  # Swagger 文档生成
    'django_extensions',  # Django 扩展工具
    'django_celery_beat',  # Celery 定时任务
]

# 自定义用户模型
AUTH_USER_MODEL = 'users.User'

INSTALLED_APPS = SHARED_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # CORS middleware
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # 静态文件压缩和缓存
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.saas.middleware.TenantMiddleware',  # SaaS 多租户上下文注入
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'djangoProjectTest.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
            os.path.join(BASE_DIR, 'apps', 'core', 'templates')
        ],
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
USE_TZ = False

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
    'EXCEPTION_HANDLER': 'utils.exceptions.handler.global_exception_handler',
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # JWT 认证（主要使用）
        'rest_framework.authentication.SessionAuthentication',  # Session 认证（浏览器页面使用）
        # 'rest_framework.authentication.BasicAuthentication',  # Basic 认证（已禁用）
        # 'users.authentication.ExpiringTokenAuthentication',  # Token 认证（已禁用）
    ],
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_RENDERER_CLASSES': (
        'utils.renderers.custom_renderer.CustomRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# JWT 配置
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=getattr(global_config, 'TOKEN_EXPIRE_HOURS', 24)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': global_config.SECRET_KEY,
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

# 缓存配置
if REDIS_CONFIG.get('enabled', False):
    try:
        import django_redis
        CACHES = {
            'default': {
                'BACKEND': 'django_redis.cache.RedisCache',
                'LOCATION': f'redis://{REDIS_CONFIG["host"]}:{REDIS_CONFIG["port"]}/{REDIS_CONFIG["db"]}',
                'OPTIONS': {
                    'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                    'PASSWORD': REDIS_CONFIG.get('password'),
                    'CONNECTION_POOL_KWARGS': {
                        'max_connections': REDIS_CONFIG['max_connections'],
                        'socket_timeout': REDIS_CONFIG['socket_timeout'],
                        'socket_connect_timeout': REDIS_CONFIG['socket_connect_timeout'],
                    },
                },
                'TIMEOUT': 60 * 30,  # 默认 30 分钟过期
            }
        }
    except ImportError:
        # django-redis 未安装，回退到内存缓存
        CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'unique-snowflake',
            }
        }
else:
    # Redis 未启用，使用内存缓存
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }

# --- RabbitMQ 消息队列配置 ---
RABBITMQ_CONFIG = global_config.rabbitmq.model_dump()

LOGIN_URL = '/api/users/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# CORS configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Allow all in dev, restrict in prod

if not CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOWED_ORIGINS = global_config.CORS_ALLOWED_ORIGINS

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

# --- 日志配置 ---
from utils.logUtils.loguruControl import LogManager, InterceptHandler
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
LogManager(log_dir=LOGS_DIR, level="DEBUG" if DEBUG else "INFO")

# Django's own logging configuration - 所有日志都转发到 loguru
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'loguru': {
            'class': 'utils.logUtils.loguruControl.InterceptHandler',
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
            'propagate': False,
        },
    }
}

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

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Shanghai'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# =====================================================
# Whitenoise 静态文件配置
# =====================================================
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
