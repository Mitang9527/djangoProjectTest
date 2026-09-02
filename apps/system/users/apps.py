from django.apps import AppConfig

class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'system.users'
    verbose_name = '用户管理'

    def ready(self) -> None:
        # 注册用户域领域事件消费者（事务 Outbox）：模块级标志防重，
        # runserver 父子进程 / 测试多次触发均安全。
        from system.users.events import register_user_event_handlers
        register_user_event_handlers()
