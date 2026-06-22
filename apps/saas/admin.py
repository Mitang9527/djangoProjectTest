"""
SaaS 后台管理系统 - Django 后台管理
"""
from django.contrib import admin
from .models import (
    Plan,
    PlanFeature,
    Tenant,
    TenantSubscription,
    TenantConfig,
    Permission,
    Role,
    TenantMember,
    Order,
    Invoice
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'price', 'max_users', 'is_active', 'is_featured', 'sort_order', 'created_at']
    list_filter = ['is_active', 'is_featured']
    search_fields = ['name', 'slug', 'description']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['is_active', 'is_featured', 'sort_order']


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 1


@admin.register(PlanFeature)
class PlanFeatureAdmin(admin.ModelAdmin):
    list_display = ['plan', 'feature_code', 'feature_name', 'is_enabled', 'created_at']
    list_filter = ['is_enabled', 'plan']
    search_fields = ['feature_code', 'feature_name']


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'status', 'plan', 'created_by', 'created_at', 'updated_at']
    list_filter = ['status', 'plan']
    search_fields = ['name', 'slug', 'domain']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TenantSubscription)
class TenantSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'plan', 'status', 'start_date', 'end_date', 'auto_renew', 'created_at']
    list_filter = ['status', 'auto_renew', 'plan']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TenantConfig)
class TenantConfigAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'key', 'category', 'created_at', 'updated_at']
    list_filter = ['category', 'tenant']
    search_fields = ['key', 'value']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'module', 'is_active', 'created_at']
    list_filter = ['module', 'is_active']
    search_fields = ['name', 'slug', 'description']
    readonly_fields = ['created_at']


class TenantMemberInline(admin.TabularInline):
    model = TenantMember
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'tenant', 'is_system', 'is_active', 'created_at']
    list_filter = ['is_system', 'is_active', 'tenant']
    search_fields = ['name', 'slug']
    filter_horizontal = ['permissions']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TenantMember)
class TenantMemberAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'user', 'role', 'is_active', 'joined_at']
    list_filter = ['is_active', 'tenant', 'role']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['joined_at']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'tenant', 'user', 'plan', 'amount', 'status', 'payment_method', 'created_at']
    list_filter = ['status', 'payment_method', 'plan']
    search_fields = ['order_number', 'tenant__name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'order', 'tenant', 'amount', 'status', 'due_date', 'created_at']
    list_filter = ['status']
    search_fields = ['invoice_number', 'order__order_number', 'tenant__name']
    readonly_fields = ['created_at', 'updated_at']
