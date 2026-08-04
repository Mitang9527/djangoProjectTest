from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from django.utils import timezone
from json import dumps as json_dumps
from .models import AuditLog, AuditExcludeModel


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """审计日志管理界面"""
    list_display = [
        'id', 
        'user', 
        'action_display', 
        'log_type_display',
        'target_model', 
        'target_id', 
        'is_tampered_display',
        'ip_address',
        'created_at'
    ]
    list_filter = [
        'action', 
        'log_type', 
        'is_tampered',
        'target_model',
        'created_at',
    ]
    search_fields = [
        'user__username', 
        'target_model', 
        'target_id', 
        'ip_address', 
        'action_info',
        'request_path'
    ]
    readonly_fields = [
        'id', 
        'user', 
        'action', 
        'log_type',
        'target_model', 
        'target_id', 
        'old_data', 
        'new_data', 
        'changes', 
        'action_info',
        'ip_address', 
        'user_agent', 
        'request_path', 
        'request_method',
        'data_hash', 
        'previous_hash', 
        'is_tampered', 
        'created_at',
        'verify_integrity'
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    list_per_page = 50
    
    actions = ['verify_chain_integrity', 'export_selected_logs']
    
    def action_display(self, obj):
        """操作显示，带颜色"""
        colors = {
            'CREATE': 'green',
            'UPDATE': 'orange',
            'DELETE': 'red',
            'LOGIN': 'blue',
            'LOGOUT': 'gray',
            'LOGIN_FAILED': 'darkred',
            'PERMISSION_CHANGE': 'purple',
            'DATA_EXPORT': 'teal',
            'SETTINGS_CHANGE': 'brown',
            'PASSWORD_CHANGE': 'crimson',
            'OTHER': 'black',
        }
        color = colors.get(obj.action, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_action_display()
        )
    action_display.short_description = '操作'
    
    def log_type_display(self, obj):
        """日志类型显示"""
        colors = {
            'MODEL': '#3498db',
            'SENSITIVE': '#e74c3c',
            'SYSTEM': '#95a5a6',
        }
        color = colors.get(obj.log_type, '#333')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 4px;">{}</span>',
            color,
            obj.get_log_type_display()
        )
    log_type_display.short_description = '类型'
    
    def is_tampered_display(self, obj):
        """是否被篡改显示"""
        if obj.is_tampered:
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠️ 已篡改</span>'
            )
        return format_html(
            '<span style="color: green;">✅ 正常</span>'
        )
    is_tampered_display.short_description = '完整性'
    
    def verify_integrity(self, obj):
        """验证当前记录完整性"""
        is_valid = obj.verify_integrity()
        if is_valid:
            return format_html(
                '<span style="color: green;">✅ 验证通过</span>'
            )
        return format_html(
            '<span style="color: red;">❌ 验证失败</span>'
        )
    verify_integrity.short_description = '完整性验证'
    
    def has_add_permission(self, request):
        """不允许添加审计日志"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """不允许修改审计日志"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """不允许删除审计日志"""
        return False
    
    @admin.action(description="验证审计日志链完整性")
    def verify_chain_integrity(self, request, queryset):
        """验证整个审计日志链的完整性"""
        tampered_logs = AuditLog.verify_chain_integrity()
        if tampered_logs:
            self.message_user(
                request,
                f"⚠️ 发现 {len(tampered_logs)} 条被篡改的审计日志！",
                level='ERROR'
            )
        else:
            self.message_user(
                request,
                "✅ 所有审计日志完整性验证通过！",
                level='SUCCESS'
            )
    
    @admin.action(description="导出选中的审计日志")
    def export_selected_logs(self, request, queryset):
        """导出选中的审计日志"""
        from django.http import HttpResponse
        import csv
        from io import StringIO
        
        f = StringIO()
        writer = csv.writer(f)
        writer.writerow([
            'ID', '用户', '操作', '类型', '目标模型', '目标ID',
            'IP地址', '请求路径', '创建时间', '是否被篡改'
        ])
        
        for log in queryset:
            writer.writerow([
                log.id,
                log.user.username if log.user else 'None',
                log.get_action_display(),
                log.get_log_type_display(),
                log.target_model or '',
                log.target_id or '',
                log.ip_address or '',
                log.request_path or '',
                log.created_at,
                '是' if log.is_tampered else '否'
            ])
        
        f.seek(0)
        response = HttpResponse(f, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="audit_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        return response


@admin.register(AuditExcludeModel)
class AuditExcludeModelAdmin(admin.ModelAdmin):
    """审计排除配置管理界面"""
    list_display = ['app_label', 'model_name', 'excluded_fields_display', 'reason', 'created_at']
    list_filter = ['app_label', 'created_at']
    search_fields = ['app_label', 'model_name', 'reason']
    
    def excluded_fields_display(self, obj):
        """显示排除的字段"""
        if obj.exclude_fields:
            return ', '.join(obj.exclude_fields)
        return '-'
    excluded_fields_display.short_description = '排除字段'


# 自定义 Admin 站点标题
admin.site.site_header = "审计日志管理系统"
admin.site.site_title = "审计日志"
admin.site.index_title = "审计日志管理"
