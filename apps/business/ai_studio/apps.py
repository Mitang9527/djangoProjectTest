from django.apps import AppConfig


class AiStudioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business.ai_studio'
    verbose_name = 'AI 创作工作室'

    def ready(self):
        # 注册信号：新用户创建时自动建额度账户并发放注册赠送
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save
        from .signals import ensure_quota_on_register
        User = get_user_model()
        post_save.connect(ensure_quota_on_register, sender=User)
