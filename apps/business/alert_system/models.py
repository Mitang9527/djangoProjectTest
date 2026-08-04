from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


class AlertChannel(models.TextChoices):
    EMAIL = 'email', '邮件'
    DINGTALK = 'dingtalk', '钉钉'
    FEISHU = 'feishu', '飞书'


class AlertLevel(models.TextChoices):
    INFO = 'info', '信息'
    WARNING = 'warning', '警告'
    ERROR = 'error', '错误'
    CRITICAL = 'critical', '严重'


class AlertStatus(models.TextChoices):
    PENDING = 'pending', '待处理'
    SENT = 'sent', '已发送'
    FAILED = 'failed', '发送失败'
    SUPPRESSED = 'suppressed', '已抑制'
    SILENCED = 'silenced', '已静默'


class AlertRule(models.Model):
    """告警规则"""

    name = models.CharField(max_length=200, verbose_name='规则名称')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    
    enabled = models.BooleanField(default=True, verbose_name='是否启用')
    
    level = models.CharField(
        max_length=20,
        choices=AlertLevel.choices,
        default=AlertLevel.WARNING,
        verbose_name='告警级别'
    )
    
    condition_type = models.CharField(
        max_length=50,
        choices=[
            ('log_level', '日志级别'),
            ('keyword', '关键词'),
            ('custom', '自定义条件'),
        ],
        default='log_level',
        verbose_name='条件类型'
    )
    
    condition_value = models.TextField(verbose_name='条件值')
    
    channels = models.JSONField(
        default=list,
        verbose_name='通知渠道',
        help_text='JSON数组，可选值：email, dingtalk, feishu'
    )
    
    escalation_rules = models.JSONField(
        default=list,
        verbose_name='升级规则',
        help_text='[{ "delay_minutes": 30, "level": "critical", "channels": [...] }]'
    )
    
    silent_periods = models.JSONField(
        default=list,
        blank=True,
        verbose_name='静默时段',
        help_text='[{ "start": "22:00", "end": "08:00" }]'
    )
    
    suppression_window = models.IntegerField(
        default=5,
        verbose_name='抑制窗口(分钟)',
        help_text='相同告警在该时间窗口内只发送一次'
    )
    
    max_occurrences = models.IntegerField(
        default=10,
        verbose_name='最大触发次数',
        help_text='超过此次数后自动抑制'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alert_rules_created',
        verbose_name='创建人'
    )

    class Meta:
        db_table = 'alert_rule'
        verbose_name = '告警规则'
        verbose_name_plural = '告警规则'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class AlertSilence(models.Model):
    """告警静默配置"""

    name = models.CharField(max_length=200, verbose_name='静默名称')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    
    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name='silences',
        null=True,
        blank=True,
        verbose_name='关联规则'
    )
    
    match_pattern = models.TextField(
        blank=True,
        null=True,
        verbose_name='匹配模式',
        help_text='告警内容匹配模式（支持正则）'
    )
    
    start_time = models.DateTimeField(verbose_name='开始时间')
    end_time = models.DateTimeField(verbose_name='结束时间')
    
    enabled = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alert_silences_created',
        verbose_name='创建人'
    )

    class Meta:
        db_table = 'alert_silence'
        verbose_name = '告警静默'
        verbose_name_plural = '告警静默'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.start_time} - {self.end_time})"

    def is_active(self) -> bool:
        now = timezone.now()
        return self.enabled and self.start_time <= now <= self.end_time


class AlertHistory(models.Model):
    """告警历史记录"""

    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name='histories',
        null=True,
        blank=True,
        verbose_name='关联规则'
    )
    
    level = models.CharField(
        max_length=20,
        choices=AlertLevel.choices,
        default=AlertLevel.WARNING,
        verbose_name='告警级别'
    )
    
    title = models.CharField(max_length=500, verbose_name='告警标题')
    content = models.TextField(verbose_name='告警内容')
    
    status = models.CharField(
        max_length=20,
        choices=AlertStatus.choices,
        default=AlertStatus.PENDING,
        verbose_name='状态'
    )
    
    channels = models.JSONField(
        default=list,
        verbose_name='发送渠道'
    )
    
    sent_channels = models.JSONField(
        default=list,
        verbose_name='已发送渠道'
    )
    
    error_message = models.TextField(blank=True, null=True, verbose_name='错误信息')
    
    occurrences = models.IntegerField(default=1, verbose_name='发生次数')
    
    first_occurred_at = models.DateTimeField(auto_now_add=True, verbose_name='首次发生时间')
    last_occurred_at = models.DateTimeField(auto_now_add=True, verbose_name='最近发生时间')
    
    acknowledged = models.BooleanField(default=False, verbose_name='是否已确认')
    acknowledged_at = models.DateTimeField(null=True, blank=True, verbose_name='确认时间')
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alerts_acknowledged',
        verbose_name='确认人'
    )
    
    resolved = models.BooleanField(default=False, verbose_name='是否已解决')
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='解决时间')
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alerts_resolved',
        verbose_name='解决人'
    )
    
    context = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='上下文信息'
    )

    class Meta:
        db_table = 'alert_history'
        verbose_name = '告警历史'
        verbose_name_plural = '告警历史'
        ordering = ['-first_occurred_at']
        indexes = [
            models.Index(fields=['-last_occurred_at']),
            models.Index(fields=['status', 'level']),
            models.Index(fields=['acknowledged', 'resolved']),
        ]

    @property
    def created_at(self):
        return self.first_occurred_at

    def __str__(self):
        return f"[{self.get_level_display()}] {self.title}"


class AlertNotificationConfig(models.Model):
    """告警通知配置"""

    name = models.CharField(max_length=200, verbose_name='配置名称')
    
    channel = models.CharField(
        max_length=20,
        choices=AlertChannel.choices,
        verbose_name='通知渠道'
    )
    
    config = models.JSONField(
        default=dict,
        verbose_name='配置信息',
        help_text='JSON格式的配置信息'
    )
    
    enabled = models.BooleanField(default=True, verbose_name='是否启用')
    is_default = models.BooleanField(default=False, verbose_name='是否默认')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'alert_notification_config'
        verbose_name = '告警通知配置'
        verbose_name_plural = '告警通知配置'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_channel_display()})"
