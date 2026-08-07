from django.contrib import admin

from .models import (
    GenerationTask, QuotaTransaction, UserQuota, RechargeOrder,
    ApiChannel, UserChannelGrant,
)


@admin.register(UserQuota)
class UserQuotaAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'frozen', 'total_granted', 'signup_granted')
    search_fields = ('user__username',)


@admin.register(QuotaTransaction)
class QuotaTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'tx_type', 'amount', 'balance_after', 'frozen_after', 'created_at')
    list_filter = ('tx_type',)


@admin.register(RechargeOrder)
class RechargeOrderAdmin(admin.ModelAdmin):
    list_display = ('order_no', 'user', 'quota_amount', 'status', 'method', 'paid_at')
    list_filter = ('status', 'method')
    search_fields = ('order_no', 'user__username')


@admin.register(GenerationTask)
class GenerationTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'kind', 'status', 'cost', 'channel', 'created_at')
    list_filter = ('status', 'kind')


@admin.register(ApiChannel)
class ApiChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'is_active', 'cost_per_call', 'created_at')
    list_filter = ('kind', 'is_active')


@admin.register(UserChannelGrant)
class UserChannelGrantAdmin(admin.ModelAdmin):
    list_display = ('user', 'channel', 'enabled', 'per_user_quota', 'used_quota', 'granted_at')
    list_filter = ('enabled', 'channel')
    search_fields = ('user__username', 'channel__name')
