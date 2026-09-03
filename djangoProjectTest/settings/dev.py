"""开发环境配置（ENV=DEV）。

继承 ``base.py``，开启 DEBUG，使用本地 SQLite，关闭数据库连接池；供本地联调
（前端 5273 / 后端 8300）使用。
"""
from .base import *
from ..model import global_config

DEBUG = True

ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# 数据库配置（开发环境，默认 SQLite）
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
DATABASES, DATABASE_ROUTERS = apply_replica(DATABASES, DATABASE_ROUTERS)


# Django Debug Toolbar 配置
INSTALLED_APPS += ['debug_toolbar']

MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

INTERNAL_IPS = ['127.0.0.1']

def _show_toolbar(request):
    """仅对浏览器访问的 HTML 页面启用 Debug Toolbar。

    历史教训：原实现对所有请求（含 /api/ 的 JSON 接口）开启，导致每个 API 请求收集
    SQL/缓存/信号/模板全部面板数据、被拖慢到秒级。API 与静态资源一律跳过。
    """
    if not DEBUG:
        return False
    path = request.path or ''
    if path.startswith(('/api/', '/media/', '/static/', '/metrics')):
        return False
    # 仅明确接受 HTML 的请求才注入 toolbar
    return 'text/html' in request.headers.get('Accept', '')


DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': _show_toolbar,
    # 测试时 DEBUG 被 Django 强制置 False，toolbar 无法工作；显式声明以通过系统检查
    'IS_RUNNING_TESTS': False,
}
