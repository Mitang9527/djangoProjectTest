from django.contrib import admin
from .models import (
    AlertRule,
    AlertSilence,
    AlertHistory,
    AlertNotificationConfig
)


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'level', 'enabled', 'created_at', 'updated_at']
    list_filter = ['enabled', 'level', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AlertSilence)
class AlertSilenceAdmin(admin.ModelAdmin):
    list_display = ['name', 'rule', 'start_time', 'end_time', 'enabled', 'is_active']
    list_filter = ['enabled', 'start_time', 'end_time']
    search_fields = ['name', 'description', 'match_pattern']
    readonly_fields = ['created_at']
    
    def is_active(self, obj):
        return obj.is_active()
    is_active.boolean = True


@admin.register(AlertHistory)
class AlertHistoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'level', 'status', 'occurrences', 'acknowledged', 'resolved', 'last_occurred_at']
    list_filter = ['level', 'status', 'acknowledged', 'resolved', 'last_occurred_at']
    search_fields = ['title', 'content']
    readonly_fields = ['first_occurred_at', 'last_occurred_at']


@admin.register(AlertNotificationConfig)
class AlertNotificationConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'channel', 'enabled', 'is_default', 'created_at']
    list_filter = ['channel', 'enabled', 'is_default']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']
