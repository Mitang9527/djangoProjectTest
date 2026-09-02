from django.apps import AppConfig


class SaasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'system.saas'
    verbose_name = 'SaaS 后台管理'
    label = 'saas'

    def ready(self):
        """注册参考完整性守卫引用（对齐 Fast-Vben-Admin reference_guards.py）。"""
        from framework.db.reference_guards import register_references
        from system.saas import models as saas_models
        from system.users.models import User

        register_references(saas_models.Role, [
            (User, ("role",)),
            (saas_models.TenantMember, ("role",)),
            (saas_models.RoleDataScopeDepartment, ("role",)),
        ])
        register_references(saas_models.Permission, [
            (saas_models.Role.permissions.through, ("permission",)),
        ])
        register_references(saas_models.Department, [
            (saas_models.TenantMember, ("department",)),
            (saas_models.RoleDataScopeDepartment, ("department",)),
        ])
        register_references(saas_models.Post, [
            (saas_models.UserPost, ("post",)),
        ])
        register_references(saas_models.Tenant, [
            (saas_models.Role, ("tenant",)),
            (saas_models.Department, ("tenant",)),
            (saas_models.Post, ("tenant",)),
            (saas_models.TenantMember, ("tenant",)),
            (saas_models.TenantSubscription, ("tenant",)),
            (saas_models.TenantConfig, ("tenant",)),
            (saas_models.Order, ("tenant",)),
            (saas_models.Invoice, ("tenant",)),
        ])
