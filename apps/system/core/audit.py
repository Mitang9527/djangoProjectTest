import copy
import threading
import functools
from typing import Any, Callable, Optional, Dict
from django.db.models import Model
from django.db.models.fields.files import FieldFile
from django.db.models.signals import pre_save, post_save, pre_delete
from django.dispatch import receiver
from django.apps import apps
from django.utils.functional import classproperty
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from loguru import logger

_local_storage = threading.local()


def set_current_request(request):
    """设置当前线程的请求对象"""
    _local_storage.request = request


def get_current_request():
    """获取当前线程的请求对象"""
    return getattr(_local_storage, 'request', None)


def get_current_user():
    """获取当前用户"""
    request = get_current_request()
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        return request.user
    return None


def _json_safe(value):
    """将 ORM 字段原始值转换为 JSON 可序列化形式（审计快照用）。

    DjangoJSONEncoder 已能处理 datetime/Decimal/UUID/Promise, 唯独无法处理
    文件字段(FieldFile/ImageFieldFile), 这里专门转换; 并对其它非预期类型做兜底,
    避免审计日志因序列化失败而整条丢失。
    """
    if isinstance(value, FieldFile):
        # 存文件名即可, 空文件记为 None
        return value.name if value else None
    if isinstance(value, Model):
        return value.pk
    return value


def get_model_snapshot(instance):
    """获取模型实例的快照"""
    data = {}
    for field in instance._meta.fields:
        value = field.value_from_object(instance)
        if hasattr(field, 'attname'):
            data[field.attname] = _json_safe(value)
    return data


def get_changes(old_data, new_data):
    """获取两个数据快照之间的差异"""
    changes = {}
    all_keys = set(old_data.keys()).union(set(new_data.keys()))
    for key in all_keys:
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if old_val != new_val:
            changes[key] = {
                'old': old_val,
                'new': new_val
            }
    return changes


def is_model_excluded(instance):
    """检查模型是否被排除审计"""
    app_label = instance._meta.app_label
    model_name = instance._meta.model_name
    
    exclude_models = {
        'core.auditlog',
        'core.auditexcludemodel',
        'admin.logentry',
        'sessions.session',
        'migrations.migration',
        'contenttypes.contenttype',
        'auth.permission',
        'django_celery_beat.*',
    }
    
    if f"{app_label}.{model_name}" in exclude_models:
        return True
    
    if hasattr(instance._meta, 'app_label'):
        for exclude in exclude_models:
            if exclude.endswith('.*') and app_label == exclude[:-2]:
                return True
    
    try:
        AuditExcludeModel = apps.get_model('core', 'AuditExcludeModel')
        return AuditExcludeModel.objects.filter(
            app_label=app_label,
            model_name=model_name
        ).exists()
    except Exception:
        return False


def get_excluded_fields(instance):
    """获取模型被排除的字段"""
    try:
        AuditExcludeModel = apps.get_model('core', 'AuditExcludeModel')
        exclude_config = AuditExcludeModel.objects.filter(
            app_label=instance._meta.app_label,
            model_name=instance._meta.model_name
        ).first()
        return exclude_config.exclude_fields if exclude_config else []
    except Exception:
        return []


def filter_excluded_fields(data, excluded_fields):
    """过滤被排除的字段"""
    if not excluded_fields:
        return data
    return {k: v for k, v in data.items() if k not in excluded_fields}


_pre_save_snapshots = {}


@receiver(pre_save)
def audit_pre_save(sender, instance, **kwargs):
    """保存前获取旧数据快照"""
    if is_model_excluded(instance):
        return
    
    try:
        if instance.pk:
            old_instance = sender.objects.filter(pk=instance.pk).first()
            if old_instance:
                excluded_fields = get_excluded_fields(instance)
                _pre_save_snapshots[id(instance)] = filter_excluded_fields(
                    get_model_snapshot(old_instance),
                    excluded_fields
                )
    except Exception as e:
        logger.error(f"Error in audit_pre_save: {e}")


@receiver(post_save)
def audit_post_save(sender, instance, created, **kwargs):
    """保存后记录审计日志"""
    if is_model_excluded(instance):
        return
    
    try:
        AuditLog = apps.get_model('core', 'AuditLog')
        request = get_current_request()
        user = get_current_user()
        excluded_fields = get_excluded_fields(instance)
        
        new_data = filter_excluded_fields(get_model_snapshot(instance), excluded_fields)
        old_data = _pre_save_snapshots.pop(id(instance), None)
        
        action = 'CREATE' if created else 'UPDATE'
        changes = None
        
        if not created and old_data:
            changes = get_changes(old_data, new_data)
            if not changes:
                return
        
        audit_log = AuditLog.objects.create(
            user=user,
            action=action,
            log_type='MODEL',
            target_model=f"{instance._meta.app_label}.{instance._meta.model_name}",
            target_id=str(instance.pk) if instance.pk else None,
            old_data=old_data if not created else None,
            new_data=new_data,
            changes=changes,
            ip_address=request.META.get('REMOTE_ADDR') if request else None,
            user_agent=request.META.get('HTTP_USER_AGENT') if request else None,
            request_path=request.path if request else None,
            request_method=request.method if request else None,
        )
        
        logger.debug(f"Audit log created: {audit_log}")
    
    except Exception as e:
        logger.error(f"Error in audit_post_save: {e}")


@receiver(pre_delete)
def audit_pre_delete(sender, instance, **kwargs):
    """删除前记录审计日志"""
    if is_model_excluded(instance):
        return
    
    try:
        AuditLog = apps.get_model('core', 'AuditLog')
        request = get_current_request()
        user = get_current_user()
        excluded_fields = get_excluded_fields(instance)
        
        old_data = filter_excluded_fields(get_model_snapshot(instance), excluded_fields)
        
        audit_log = AuditLog.objects.create(
            user=user,
            action='DELETE',
            log_type='MODEL',
            target_model=f"{instance._meta.app_label}.{instance._meta.model_name}",
            target_id=str(instance.pk) if instance.pk else None,
            old_data=old_data,
            ip_address=request.META.get('REMOTE_ADDR') if request else None,
            user_agent=request.META.get('HTTP_USER_AGENT') if request else None,
            request_path=request.path if request else None,
            request_method=request.method if request else None,
        )
        
        logger.debug(f"Audit log created for delete: {audit_log}")
    
    except Exception as e:
        logger.error(f"Error in audit_pre_delete: {e}")


# ============================================
# 敏感操作审计
# ============================================

def log_sensitive_action(action: str, action_info: Optional[Dict] = None, 
                         user=None, target_model=None, target_id=None):
    """记录敏感操作审计日志"""
    try:
        AuditLog = apps.get_model('core', 'AuditLog')
        request = get_current_request()
        
        if user is None:
            user = get_current_user()
        
        audit_log = AuditLog.objects.create(
            user=user,
            action=action,
            log_type='SENSITIVE',
            target_model=target_model,
            target_id=target_id,
            action_info=action_info or {},
            ip_address=request.META.get('REMOTE_ADDR') if request else None,
            user_agent=request.META.get('HTTP_USER_AGENT') if request else None,
            request_path=request.path if request else None,
            request_method=request.method if request else None,
        )
        
        logger.info(f"Sensitive action logged: {action} by {user}")
        return audit_log
    
    except Exception as e:
        logger.error(f"Error logging sensitive action: {e}")
        return None


def sensitive_operation(action: str, action_info_key: Optional[str] = None):
    """
    敏感操作装饰器
    使用示例:
    @sensitive_operation('DATA_EXPORT')
    def export_data(request):
        ...
    """
    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            result = view_func(request, *args, **kwargs)
            
            info = {}
            if action_info_key and hasattr(result, action_info_key):
                info[action_info_key] = getattr(result, action_info_key)
            
            log_sensitive_action(
                action=action,
                action_info=info,
                user=request.user if request.user.is_authenticated else None
            )
            
            return result
        return wrapped_view
    return decorator


@receiver(user_logged_in)
def audit_user_login(sender, request, user, **kwargs):
    """用户登录审计"""
    log_sensitive_action(
        action='LOGIN',
        user=user,
        action_info={'login_method': getattr(sender, '__name__', 'unknown')}
    )


@receiver(user_logged_out)
def audit_user_logout(sender, request, user, **kwargs):
    """用户登出审计"""
    log_sensitive_action(
        action='LOGOUT',
        user=user
    )


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request, **kwargs):
    """登录失败审计"""
    log_sensitive_action(
        action='LOGIN_FAILED',
        action_info={'username': credentials.get('username', 'unknown')}
    )


def audit_permission_change(user, changed_permission, old_value, new_value):
    """权限变更审计"""
    log_sensitive_action(
        action='PERMISSION_CHANGE',
        user=user,
        action_info={
            'permission': changed_permission,
            'old_value': old_value,
            'new_value': new_value
        }
    )


def audit_data_export(user, export_type, export_count=None):
    """数据导出审计"""
    log_sensitive_action(
        action='DATA_EXPORT',
        user=user,
        action_info={
            'export_type': export_type,
            'export_count': export_count
        }
    )


def audit_settings_change(user, settings_changed, old_settings, new_settings):
    """配置变更审计"""
    log_sensitive_action(
        action='SETTINGS_CHANGE',
        user=user,
        action_info={
            'settings_changed': settings_changed,
            'old_settings': old_settings,
            'new_settings': new_settings
        }
    )


def audit_password_change(user):
    """密码变更审计"""
    log_sensitive_action(
        action='PASSWORD_CHANGE',
        user=user,
        action_info={'changed_at': 'timestamp'}
    )
