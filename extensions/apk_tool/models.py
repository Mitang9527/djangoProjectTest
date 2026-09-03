import uuid
from django.db import models
from django.conf import settings


class BuildTask(models.Model):
    """APK 构建任务"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 任务状态
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('decompiling', '反编译中'),
        ('configuring', '配置中'),
        ('building', '构建中'),
        ('signing', '签名中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # APK 类型（内置模板包 DEF_APK 已移除，仅支持自定义上传）
    APK_TYPE_CHOICES = [
        ('custom', '自定义 APK'),
    ]
    apk_type = models.CharField(max_length=20, choices=APK_TYPE_CHOICES, default='custom')

    # 自定义 APK 上传路径
    custom_apk = models.FileField(upload_to='apk_tool/uploads/', blank=True, null=True)

    # 配置参数
    env_key = models.CharField(max_length=50, blank=True, default='domestic_v2')
    login_type = models.CharField(max_length=20, blank=True, default='account')
    map_type = models.CharField(max_length=30, blank=True, default='none')
    sound_codec = models.CharField(max_length=30, blank=True, default='opus')
    dsp_provider = models.CharField(max_length=30, blank=True, default='default')
    launcher_module = models.CharField(max_length=20, blank=True, default='none')
    recorder_enable = models.BooleanField(default=False)
    tone_enabled = models.BooleanField(default=True)
    tts_enabled = models.BooleanField(default=True)
    device_model = models.CharField(max_length=50, blank=True, default='')
    terminal_config = models.CharField(max_length=50, blank=True, default='')

    # 构建结果
    package_name = models.CharField(max_length=100, blank=True)
    apk_name = models.CharField(max_length=200, blank=True)
    apk_path = models.CharField(max_length=500, blank=True)
    apk_relative_path = models.CharField(max_length=500, blank=True)
    apk_size = models.PositiveBigIntegerField(default=0)

    # 构建日志
    build_log = models.TextField(blank=True, default='')

    # 时间
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # 创建者
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='apk_build_tasks',
    )

    class Meta:
        db_table = 'apk_tool_build_task'
        ordering = ['-created_at']
        verbose_name = 'APK 构建任务'
        verbose_name_plural = 'APK 构建任务'

    def __str__(self):
        return f'{self.apk_type} - {self.status} - {self.created_at.strftime("%Y%m%d%H%M")}'
