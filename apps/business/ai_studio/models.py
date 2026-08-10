"""AI 创作工作室 - 数据模型

包含三张核心表：
- UserQuota       用户额度（可用 / 冻结）
- QuotaTransaction 额度流水账（不可变，用于对账与按量计费）
- GenerationTask  生成任务（图片 / 视频，状态机驱动）
"""
from django.conf import settings
from django.db import models
import uuid


class UserQuota(models.Model):
    """用户 AI 额度账户"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_quota',
        verbose_name='用户',
    )
    balance = models.IntegerField(default=0, verbose_name='可用额度')
    frozen = models.IntegerField(default=0, verbose_name='冻结额度')
    total_granted = models.IntegerField(default=0, verbose_name='累计获得额度')
    signup_granted = models.BooleanField(default=False, verbose_name='已发放注册赠送')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'AI 额度'
        verbose_name_plural = 'AI 额度'

    def __str__(self):
        return f'{self.user.username} 额度(可用={self.balance}, 冻结={self.frozen})'


class QuotaTransaction(models.Model):
    """额度变动流水（只增不改，作为对账与计费依据）"""

    TX_TYPE = (
        ('GRANT', '赠送'),
        ('RECHARGE', '充值'),
        ('ADMIN_GRANT', '管理员发放'),
        ('ADMIN_DEDUCT', '管理员扣减'),
        ('FREEZE', '冻结'),
        ('CONFIRM', '确认扣减'),
        ('REFUND', '返还'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_quota_tx',
        verbose_name='用户',
    )
    tx_type = models.CharField(max_length=16, choices=TX_TYPE, verbose_name='类型')
    amount = models.IntegerField(verbose_name='变动额度')
    balance_after = models.IntegerField(verbose_name='变动后可用')
    frozen_after = models.IntegerField(verbose_name='变动后冻结')
    task = models.ForeignKey(
        'GenerationTask',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        verbose_name='关联任务',
    )
    remark = models.CharField(max_length=200, blank=True, verbose_name='备注')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '额度流水'
        verbose_name_plural = '额度流水'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} {self.tx_type} {self.amount}'


class GenerationTask(models.Model):
    """AI 生成任务（图片 / 视频）"""

    STATUS = (
        ('PENDING', '待处理'),
        ('RUNNING', '生成中'),
        ('SUCCESS', '成功'),
        ('FAILED', '失败'),
    )
    KIND = (
        ('IMAGE', '图片'),
        ('VIDEO', '视频'),
    )
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name='任务ID',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_tasks',
        verbose_name='用户',
    )
    kind = models.CharField(max_length=10, choices=KIND, default='IMAGE', verbose_name='类型')
    prompt = models.TextField(blank=True, verbose_name='描述需求')
    ref_image = models.TextField(blank=True, null=True, verbose_name='参考图(base64/url)')
    first_frame = models.ImageField(
        upload_to='ai_studio/first_frames/', blank=True, null=True,
        verbose_name='视频首帧(上传)',
        help_text='视频生成时由用户上传的首帧图像（image-to-video），优先于 ref_image 与自动出图',
    )
    style = models.CharField(max_length=30, blank=True, default='', verbose_name='风格')
    size = models.CharField(max_length=10, blank=True, default='1:1', verbose_name='尺寸')
    resolution = models.CharField(max_length=10, blank=True, default='standard', verbose_name='分辨率')
    count = models.IntegerField(default=1, verbose_name='数量')
    cost = models.IntegerField(default=0, verbose_name='消耗额度')
    status = models.CharField(max_length=10, choices=STATUS, default='PENDING', verbose_name='状态')
    result_urls = models.JSONField(default=list, blank=True, verbose_name='生成结果')
    error_msg = models.TextField(blank=True, null=True, verbose_name='错误信息')
    error_code = models.CharField(
        max_length=64, blank=True, null=True, verbose_name='错误码',
        help_text='标准化错误码（如 API_KEY_INVALID/QUOTA_EXCEEDED/NO_FIRST_FRAME），对应 error 对象',
    )
    celery_task_id = models.CharField(max_length=64, blank=True, null=True, verbose_name='Celery任务ID')
    external_task_id = models.CharField(
        max_length=255, blank=True, null=True, verbose_name='第三方任务ID',
        help_text='第三方异步任务标识（如 Veo operation name），便于回调/查询',
    )
    channel = models.ForeignKey(
        'ApiChannel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
        verbose_name='关联渠道/Agent',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(blank=True, null=True, verbose_name='完成时间')

    class Meta:
        verbose_name = '生成任务'
        verbose_name_plural = '生成任务'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.id} {self.kind} {self.status}'


class RechargeOrder(models.Model):
    """充值订单（记账式 MVP：创建即视为已支付）"""

    STATUS = (
        ('PENDING', '待支付'),
        ('PAID', '已支付'),
        ('CANCELLED', '已取消'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_recharge_orders',
        verbose_name='用户',
    )
    order_no = models.CharField(max_length=32, unique=True, verbose_name='订单号')
    quota_amount = models.IntegerField(verbose_name='充值额度')
    status = models.CharField(max_length=10, choices=STATUS, default='PENDING', verbose_name='状态')
    method = models.CharField(max_length=20, default='mock', verbose_name='支付方式')
    remark = models.CharField(max_length=200, blank=True, verbose_name='备注')
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(blank=True, null=True, verbose_name='支付时间')

    class Meta:
        verbose_name = '充值订单'
        verbose_name_plural = '充值订单'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order_no} {self.user.username} +{self.quota_amount} {self.status}'


class ApiChannel(models.Model):
    """已接入的 API 渠道 / 自建 agent 目录（由管理员维护）"""

    KIND = (
        ('API', 'API 渠道'),
        ('AGENT', '自建 Agent'),
    )
    name = models.CharField(max_length=100, verbose_name='名称')
    kind = models.CharField(max_length=10, choices=KIND, default='API', verbose_name='类型')
    is_active = models.BooleanField(default=True, verbose_name='是否对用户开放')
    description = models.TextField(blank=True, verbose_name='简介')
    cost_per_call = models.PositiveIntegerField(default=0, verbose_name='每次调用消耗额度(按张)')
    config = models.JSONField(default=dict, blank=True, verbose_name='配置(端点/模型/密钥引用)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'API 渠道/Agent'
        verbose_name_plural = 'API 渠道/Agent'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_kind_display()})'


class UserChannelGrant(models.Model):
    """用户可使用的渠道/Agent 授权（管理员控制点）

    语义：channel.is_active 且 enabled 且（无 per_user_quota 或 used_quota < per_user_quota）
          → 用户可使用该渠道。管理员不受授权限制。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='channel_grants',
        verbose_name='用户',
    )
    channel = models.ForeignKey(
        ApiChannel,
        on_delete=models.CASCADE,
        related_name='grants',
        verbose_name='渠道/Agent',
    )
    enabled = models.BooleanField(default=True, verbose_name='是否允许使用')
    per_user_quota = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='专属额度上限(可选, 按累计消耗计)')
    used_quota = models.PositiveIntegerField(default=0, verbose_name='已用额度(累计消耗)')
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='授权人')
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '用户渠道授权'
        verbose_name_plural = '用户渠道授权'
        unique_together = ('user', 'channel')

    def __str__(self):
        return f'{self.user.username} -> {self.channel.name} ({"允许" if self.enabled else "禁止"})'
