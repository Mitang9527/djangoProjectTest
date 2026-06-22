from .base import *
from ..model import global_config

DEBUG = True

ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

DATABASES = {
    'default': {
        'ENGINE': global_config.db.engine,
        'NAME': BASE_DIR / global_config.db.name,
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
