from .base import *
from ..model import global_config

DEBUG = False

ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# =====================================================
# 数据库配置（生产环境）
# 启用 DB 连接池（framework.db）
# =====================================================
DATABASES = {
    'default': {
        # 使用 django-prometheus 包装的引擎，自动采集 DB 指标
        'ENGINE': 'django_prometheus.db.backends.' + global_config.db.engine.split('.')[-1],
        'NAME': global_config.db.name,
        'USER': global_config.db.user,
        'PASSWORD': global_config.db.password,
        'HOST': global_config.db.host,
        'PORT': global_config.db.port,
        'CONN_MAX_AGE': DB_POOL_DEFAULT_OPTIONS['max_idle'],
        'CONN_HEALTH_CHECKS': True,
        # ✅ framework.db 连接池配置：必须放在顶层（_pool），
        # 绝不能放进 OPTIONS，否则 OPTIONS 会被 **conn_params 透传给驱动，
        # 触发 TypeError: 'pool' is an invalid keyword argument 崩溃
        '_pool': {
            # 生产环境默认开启池
            'enabled':   DB_POOL_DEFAULT_OPTIONS['enabled'],
            'min_size':  DB_POOL_DEFAULT_OPTIONS['min_size'],
            'max_size':  DB_POOL_DEFAULT_OPTIONS['max_size'],
            'timeout':   DB_POOL_DEFAULT_OPTIONS['timeout'],
            'max_idle':  DB_POOL_DEFAULT_OPTIONS['max_idle'],
            'max_lifetime': DB_POOL_DEFAULT_OPTIONS['max_lifetime'],
            'pre_ping':  DB_POOL_DEFAULT_OPTIONS['pre_ping'],
        },
    }
}

# 读写分离：配置 DB_REPLICA_URL 后自动注入 replica 库 + PrimaryReplicaRouter；
# 未配置时保持单库（default），零风险。
from framework.db.replica import install_replica  # noqa: E402

DATABASES, DATABASE_ROUTERS = install_replica(DATABASES, DATABASE_ROUTERS)

# Security settings for production
SECURE_SSL_REDIRECT = global_config.SECURE_SSL_REDIRECT
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HSTS settings
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Proxy settings (if behind Nginx/Apache)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Static and Media (继承 base.py 配置)
# STATIC_ROOT / MEDIA_ROOT 已在 base.py 中定义
