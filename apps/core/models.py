from django.db import models
from django.conf import settings

class AuditLog(models.Model):
    """
    操作审计日志模型
    """
    ACTION_CHOICES = (
        ('CREATE', '新增'),
        ('UPDATE', '修改'),
        ('DELETE', '删除'),
        ('OTHER', '其他'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, verbose_name="操作行为")
    target_model = models.CharField(max_length=100, verbose_name="目标模型")
    target_id = models.CharField(max_length=50, null=True, blank=True, verbose_name="目标ID")
    action_info = models.JSONField(verbose_name="详细信息", null=True, blank=True)
    ip_address = models.GenericIPAddressField(verbose_name="IP地址", null=True, blank=True)
    user_agent = models.TextField(verbose_name="浏览器指纹", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        db_table = 'core_audit_log'
        verbose_name = '审计日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.action} - {self.target_model}"
