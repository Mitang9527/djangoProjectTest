from django.apps import AppConfig


class ApkToolConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apk_tool'
    verbose_name = 'APK 定制工具'

    def ready(self):
        # 确保 services 模块被加载
        pass
