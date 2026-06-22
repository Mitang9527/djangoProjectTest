from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'  # Since we added 'apps' to sys.path, we can use 'core' directly
    verbose_name = '核心应用'
