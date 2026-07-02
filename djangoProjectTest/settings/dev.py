from .base import *
from ..model import global_config

DEBUG = True

ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# =====================================================
# 数据库配置（开发环境，默认 SQLite）
# =====================================================
DATABASES = {
    'default': {
        'ENGINE': global_config.db.engine,
        'NAME': BASE_DIR / global_config.db.name,
        # ✅ utils.db 连接池配置：必须放在顶层（_pool），
        # 绝不能放进 OPTIONS，否则 OPTIONS 会被 **conn_params 透传给驱动，
        # 触发 TypeError: 'pool' is an invalid keyword argument 崩溃
        '_pool': {
            # 开发环境默认关闭池，避免初始化报错
            'enabled': DB_POOL_DEFAULT_OPTIONS['enabled'],
            'min_size': 1,
            'max_size': 5,
        },
    }
}

CORS_ALLOW_ALL_ORIGINS = True

# =====================================================
# Django Debug Toolbar 配置
# =====================================================
INSTALLED_APPS += ['debug_toolbar']

MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

INTERNAL_IPS = ['127.0.0.1']

DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG,
}
