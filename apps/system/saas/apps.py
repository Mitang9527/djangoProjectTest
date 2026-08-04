from django.apps import AppConfig


class SaasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'system.saas'
    verbose_name = 'SaaS 后台管理'
    label = 'saas'
