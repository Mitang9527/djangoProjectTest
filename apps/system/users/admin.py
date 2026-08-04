from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class MyUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'nickname', 'mobile', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'nickname', 'mobile')
    fieldsets = UserAdmin.fieldsets + (
        ('扩展信息', {'fields': ('nickname', 'mobile', 'avatar')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('扩展信息', {'fields': ('nickname', 'mobile', 'avatar')}),
    )
