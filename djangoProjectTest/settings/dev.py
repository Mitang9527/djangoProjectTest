from .base import *
from ..model import global_config

DEBUG = True

ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# =====================================================
# 数据库配置（开发环境，默认 SQLite）
# =====================================================
DATABASES = {
    'default': {
        'ENGINE': 'django_prometheus.db.backends.sqlite3',
        'NAME': BASE_DIR / global_config.db.name,
        '_pool': {
            # 开发环境默认关闭池，避免初始化报错
            'enabled': DB_POOL_DEFAULT_OPTIONS['enabled'],
            'min_size': 1,
            'max_size': 5,
        },
    }
}

# 读写分离：配置 DB_REPLICA_URL 后自动注入 replica 库 + PrimaryReplicaRouter；
# 未配置时保持单库（default），零风险。
from framework.db.replica import install_replica  # noqa: E402

DATABASES, DATABASE_ROUTERS = install_replica(DATABASES, DATABASE_ROUTERS)

CORS_ALLOW_ALL_ORIGINS = True

# =====================================================
# Django Debug Toolbar 配置
# =====================================================
INSTALLED_APPS += ['debug_toolbar']

MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

INTERNAL_IPS = ['127.0.0.1']

def _show_toolbar(request):
    """仅对浏览器访问的 HTML 页面启用 Debug Toolbar。

    原实现对所有请求（含 /api/ 的 JSON 接口）都开启，导致 toolbar 为每个 API
    请求收集 SQL / 缓存 / 信号 / 模板等全部面板数据，单次请求被拖慢到秒级，
    前端表现为“点了没反应”。API 与静态资源一律跳过。
    """
    if not DEBUG:
        return False
    path = request.path or ''
    if path.startswith(('/api/', '/media/', '/static/', '/metrics')):
        return False
    # 只有明确接受 HTML 的请求才注入 toolbar
    return 'text/html' in request.headers.get('Accept', '')


DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': _show_toolbar,
}
