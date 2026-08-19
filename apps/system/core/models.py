import hashlib
import json
import secrets
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from framework.drf.queryset import TimestampMixin


class AuditLog(models.Model):
    """
    增强版审计日志模型
    """
    ACTION_CHOICES = (
        ('CREATE', '新增'),
        ('UPDATE', '修改'),
        ('DELETE', '删除'),
        ('LOGIN', '登录'),
        ('LOGOUT', '登出'),
        ('LOGIN_FAILED', '登录失败'),
        ('PERMISSION_CHANGE', '权限变更'),
        ('DATA_EXPORT', '数据导出'),
        ('SETTINGS_CHANGE', '配置变更'),
        ('PASSWORD_CHANGE', '密码变更'),
        ('OTHER', '其他'),
    )

    LOG_TYPE_CHOICES = (
        ('MODEL', '模型操作'),
        ('SENSITIVE', '敏感操作'),
        ('SYSTEM', '系统操作'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="操作行为")
    log_type = models.CharField(max_length=10, choices=LOG_TYPE_CHOICES, default='MODEL', verbose_name="日志类型")
    target_model = models.CharField(max_length=100, verbose_name="目标模型", null=True, blank=True)
    target_id = models.CharField(max_length=100, null=True, blank=True, verbose_name="目标ID")
    old_data = models.JSONField(verbose_name="变更前数据", null=True, blank=True, encoder=DjangoJSONEncoder)
    new_data = models.JSONField(verbose_name="变更后数据", null=True, blank=True, encoder=DjangoJSONEncoder)
    changes = models.JSONField(verbose_name="变更详情", null=True, blank=True, encoder=DjangoJSONEncoder)
    action_info = models.JSONField(verbose_name="详细信息", null=True, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField(verbose_name="IP地址", null=True, blank=True)
    user_agent = models.TextField(verbose_name="浏览器指纹", null=True, blank=True)
    request_path = models.CharField(max_length=500, null=True, blank=True, verbose_name="请求路径")
    request_method = models.CharField(max_length=10, null=True, blank=True, verbose_name="请求方法")
    data_hash = models.CharField(max_length=128, verbose_name="数据哈希", null=True, blank=True, db_index=True)
    previous_hash = models.CharField(max_length=128, verbose_name="上一条哈希", null=True, blank=True, db_index=True)
    is_tampered = models.BooleanField(default=False, verbose_name="是否被篡改")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间", db_index=True)

    class Meta:
        db_table = 'core_audit_log'
        verbose_name = '审计日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['target_model', 'target_id']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.target_model or self.log_type}"

    def compute_hash(self):
        """计算当前记录的哈希值"""
        data = {
            'user_id': str(self.user.id) if self.user else None,
            'action': self.action,
            'log_type': self.log_type,
            'target_model': self.target_model,
            'target_id': self.target_id,
            'old_data': self.old_data,
            'new_data': self.new_data,
            'changes': self.changes,
            'action_info': self.action_info,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        data_str = json.dumps(data, sort_keys=True, ensure_ascii=False, cls=DjangoJSONEncoder)
        if self.previous_hash:
            data_str = f"{self.previous_hash}{data_str}"
        return hashlib.sha512(data_str.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """重写 save 方法，自动计算哈希"""
        if not self.data_hash:
            if not self.previous_hash:
                last_log = AuditLog.objects.order_by('-created_at').first()
                if last_log:
                    self.previous_hash = last_log.data_hash
            self.data_hash = self.compute_hash()
        super().save(*args, **kwargs)

    def verify_integrity(self):
        """验证当前记录的完整性"""
        return self.compute_hash() == self.data_hash

    @classmethod
    def verify_chain_integrity(cls):
        """验证整个审计日志链的完整性"""
        logs = cls.objects.order_by('created_at')
        previous_hash = None
        tampered_logs = []
        
        for log in logs:
            if previous_hash and log.previous_hash != previous_hash:
                log.is_tampered = True
                tampered_logs.append(log)
            elif not log.verify_integrity():
                log.is_tampered = True
                tampered_logs.append(log)
            else:
                log.is_tampered = False
            
            previous_hash = log.data_hash
            log.save(update_fields=['is_tampered'])
        
        return tampered_logs


class AuditExcludeModel(models.Model):
    """排除审计的模型配置"""
    app_label = models.CharField(max_length=100, verbose_name="应用标签")
    model_name = models.CharField(max_length=100, verbose_name="模型名称")
    exclude_fields = models.JSONField(verbose_name="排除字段", null=True, blank=True, default=list)
    reason = models.TextField(verbose_name="排除原因", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_audit_exclude'
        verbose_name = '审计排除配置'
        verbose_name_plural = verbose_name
        unique_together = ('app_label', 'model_name')

    def __str__(self):
        return f"{self.app_label}.{self.model_name}"


class APIKey(TimestampMixin, models.Model):
    """
    带时效性的访问密钥（Access Key）。

    用于「先同步校验密钥正确性 + 时效性，再返回受保护信息」的接口：
    - key        明文密钥，仅签发时可见一次，之后不再回显
    - key_hash   SHA256 哈希，用于查询与比对（库内不保留可检索的明文）
    - is_active  是否启用（可主动吊销，无需改密钥）
    - expires_at 过期时间；None 表示永不过期（时效性由签发时 ttl 决定）
    - last_used_at 最近一次成功使用时间
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name="所属用户",
    )
    name = models.CharField(max_length=100, verbose_name="标识用途", help_text="例如：报表导出服务")
    key = models.CharField(
        max_length=128, unique=True,
        verbose_name="明文密钥", help_text="仅签发时可见一次",
    )
    key_hash = models.CharField(
        max_length=64, unique=True, db_index=True,
        verbose_name="SHA256 哈希",
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="最近使用时间")

    class Meta:
        db_table = "core_apikey"
        verbose_name = "访问密钥"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user})"

    def is_expired(self) -> bool:
        """是否已过期（expires_at 非空且已过当前时间）。"""
        return self.expires_at is not None and timezone.now() > self.expires_at

    def is_usable(self) -> bool:
        """当前是否可用：启用且未过期。"""
        return self.is_active and not self.is_expired()

    @staticmethod
    def hash_key(key: str) -> str:
        """对明文密钥做 SHA256 哈希。"""
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def issue(cls, user, name: str, ttl_seconds: int = None, prefix: str = "sk-") -> "APIKey":
        """
        签发一个带时效性的密钥。

        Args:
            user:        所属用户实例
            name:        用途标识
            ttl_seconds: 有效秒数；None/0 表示永不过期
            prefix:      密钥前缀
        Returns:
            APIKey 实例，实例.key 为明文（仅此处可见一次）
        """
        raw = f"{prefix}{secrets.token_hex(16)}"
        expires_at = None
        if ttl_seconds:
            expires_at = timezone.now() + timedelta(seconds=ttl_seconds)
        return cls.objects.create(
            user=user,
            name=name,
            key=raw,
            key_hash=cls.hash_key(raw),
            expires_at=expires_at,
        )
