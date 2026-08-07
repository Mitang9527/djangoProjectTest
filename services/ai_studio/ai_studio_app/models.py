"""AI 创作工作室 - 数据模型（身份解耦版）

与 monolith 版的核心差异：不再持有 ``User`` 外键，改为存 ``user_id``（来自 JWT
的 user_id 声明）+ ``username`` 快照。这样本服务无需任何用户表，完全依赖主平台
的鉴权结果。
"""
import uuid

from django.db import models


class UserQuota(models.Model):
    """用户 AI 额度账户（按 user_id 维度）"""

    user_id = models.CharField(max_length=64, unique=True, db_index=True, verbose_name="用户ID")
    username = models.CharField(max_length=150, blank=True, default="", verbose_name="用户名快照")
    balance = models.IntegerField(default=0, verbose_name="可用额度")
    frozen = models.IntegerField(default=0, verbose_name="冻结额度")
    total_granted = models.IntegerField(default=0, verbose_name="累计获得额度")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI 额度"
        verbose_name_plural = "AI 额度"

    def __str__(self):
        return f"{self.username or self.user_id} 额度(可用={self.balance}, 冻结={self.frozen})"


class QuotaTransaction(models.Model):
    """额度变动流水（只增不改，作为对账与计费依据）"""

    TX_TYPE = (
        ("GRANT", "赠送"),
        ("FREEZE", "冻结"),
        ("CONFIRM", "确认扣减"),
        ("REFUND", "返还"),
    )
    user_id = models.CharField(max_length=64, db_index=True, verbose_name="用户ID")
    username = models.CharField(max_length=150, blank=True, default="", verbose_name="用户名快照")
    tx_type = models.CharField(max_length=10, choices=TX_TYPE, verbose_name="类型")
    amount = models.IntegerField(verbose_name="变动额度")
    balance_after = models.IntegerField(verbose_name="变动后可用")
    frozen_after = models.IntegerField(verbose_name="变动后冻结")
    task = models.ForeignKey(
        "GenerationTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="关联任务",
    )
    remark = models.CharField(max_length=200, blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "额度流水"
        verbose_name_plural = "额度流水"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.username or self.user_id} {self.tx_type} {self.amount}"


class GenerationTask(models.Model):
    """AI 生成任务（图片 / 视频）"""

    STATUS = (
        ("PENDING", "待处理"),
        ("RUNNING", "生成中"),
        ("SUCCESS", "成功"),
        ("FAILED", "失败"),
    )
    KIND = (
        ("IMAGE", "图片"),
        ("VIDEO", "视频"),
    )
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="任务ID",
    )
    user_id = models.CharField(max_length=64, db_index=True, verbose_name="用户ID")
    username = models.CharField(max_length=150, blank=True, default="", verbose_name="用户名快照")
    kind = models.CharField(max_length=10, choices=KIND, default="IMAGE", verbose_name="类型")
    prompt = models.TextField(blank=True, verbose_name="描述需求")
    ref_image = models.TextField(blank=True, null=True, verbose_name="参考图(base64/url)")
    style = models.CharField(max_length=30, blank=True, default="", verbose_name="风格")
    size = models.CharField(max_length=10, blank=True, default="1:1", verbose_name="尺寸")
    resolution = models.CharField(max_length=10, blank=True, default="standard", verbose_name="分辨率")
    count = models.IntegerField(default=1, verbose_name="数量")
    cost = models.IntegerField(default=0, verbose_name="消耗额度")
    status = models.CharField(max_length=10, choices=STATUS, default="PENDING", verbose_name="状态")
    result_urls = models.JSONField(default=list, blank=True, verbose_name="生成结果")
    error_msg = models.TextField(blank=True, null=True, verbose_name="错误信息")
    celery_task_id = models.CharField(max_length=64, blank=True, null=True, verbose_name="Celery任务ID")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(blank=True, null=True, verbose_name="完成时间")

    class Meta:
        verbose_name = "生成任务"
        verbose_name_plural = "生成任务"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.id} {self.kind} {self.status}"
