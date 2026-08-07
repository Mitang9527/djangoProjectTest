from django.apps import AppConfig


class AiGatewayConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business.ai_gateway'
    verbose_name = 'AI 网关（主平台 → AI 服务 MQ 入口）'
