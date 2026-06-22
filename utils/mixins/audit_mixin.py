from django.apps import apps
from loguru import logger
import json

class AuditLogMixin:
    """
    审计日志 Mixin，用于 ViewSet 自动记录操作日志
    """
    def perform_create(self, serializer):
        instance = serializer.save()
        self._record_audit_log('CREATE', instance)
        return instance

    def perform_update(self, serializer):
        instance = serializer.save()
        self._record_audit_log('UPDATE', instance)
        return instance

    def perform_destroy(self, instance):
        target_id = getattr(instance, 'pk', None)
        self._record_audit_log('DELETE', instance, target_id=target_id)
        instance.delete()

    def _record_audit_log(self, action, instance, target_id=None):
        try:
            # 动态获取模型，避免导入路径导致的 app_label 错误或 IDE 报红
            AuditLog = apps.get_model('core', 'AuditLog')
            
            request = self.request
            user = request.user if request.user.is_authenticated else None
            
            # 获取 IP 地址
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
            
            # 获取目标信息
            target_model = instance._meta.model_name
            tid = target_id or getattr(instance, 'pk', None)
            
            # 构建详情（可以根据需要扩展）
            info = {
                "path": request.path,
                "method": request.method,
                "app_label": instance._meta.app_label,
            }

            AuditLog.objects.create(
                user=user,
                action=action,
                target_model=target_model,
                target_id=str(tid) if tid else None,
                action_info=info,
                ip_address=ip,
                user_agent=request.META.get('HTTP_USER_AGENT'),
            )
            logger.success(f"审计日志记录成功: {user} - {action} - {target_model}")
        except Exception as e:
            logger.error(f"审计日志记录失败: {str(e)}")
