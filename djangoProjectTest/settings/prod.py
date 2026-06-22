from .base import *
from ..model import global_config

DEBUG = False

ALLOWED_HOSTS = global_config.ALLOWED_HOSTS

# Production database configuration
DATABASES = {
    'default': {
        'ENGINE': global_config.db.engine,
        'NAME': global_config.db.name,
        'USER': global_config.db.user,
        'PASSWORD': global_config.db.password,
        'HOST': global_config.db.host,
        'PORT': global_config.db.port,
    }
}

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

# Static and Media
STATIC_ROOT = os.path.join(BASE_DIR, 'static_root')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
