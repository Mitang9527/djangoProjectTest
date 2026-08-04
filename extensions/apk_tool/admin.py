from django.contrib import admin
from .models import BuildTask


@admin.register(BuildTask)
class BuildTaskAdmin(admin.ModelAdmin):
    list_display = ['id', 'apk_type', 'status', 'device_model', 'apk_name', 'creator', 'created_at']
    list_filter = ['status', 'apk_type', 'created_at']
    search_fields = ['device_model', 'apk_name', 'package_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
