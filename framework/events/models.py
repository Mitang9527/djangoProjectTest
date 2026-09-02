"""
事务 Outbox 三表模型（对齐 Fast-Vben-Admin 的 delivery/inbox 状态机）。

设计目标：业务事务内写入事件 → worker 按「投递目标」逐个投递，保证：
  - 至少一次投递（at-least-once）：租约锁 + 失败重试 + 指数退避；
  - 恰好一次消费（幂等）：InboxReceipt 记录已消费凭证，重投跳过；
  - 死信隔离：投递超限进入 DEAD_LETTER，可 requeue_dead_letter 人工恢复；
  - 多目标扇出：一个事件可注册多个 consumer / 外部 broker 目标。

三表职责：
  OutboxEvent    事件主表：业务只关心"事件本身"（类型 / 载荷 / 状态）。
  EventDelivery  投递目标表：事件 -> 每个 consumer 的投递状态（租约 / 重试 / 死信）。
  InboxReceipt   消费凭证表：consumer 已成功消费 event 的幂等记录。

状态机：
  OutboxEvent:    PENDING -> COMPLETE | DEAD_LETTER
  EventDelivery:  PENDING -> PROCESSING -> DELIVERED | DEAD_LETTER（失败退避回 PENDING）

说明：
  - app_label='framework'，需 settings.INSTALLED_APPS 含 'framework' 并生成迁移；
  - SQLite（开发/测试）下 select_for_update 为 no-op，租约锁仍可用（单写者）；
    PostgreSQL 下启用 skip_locked 支持多 worker 并发抢单。
"""
from django.db import models
from django.utils import timezone


class OutboxEventStatus(models.TextChoices):
    PENDING = "PENDING", "待投递"
    COMPLETE = "COMPLETE", "已完成"
    DEAD_LETTER = "DEAD_LETTER", "死信"


class EventDeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "待投递"
    PROCESSING = "PROCESSING", "投递中"
    DELIVERED = "DELIVERED", "已投递"
    DEAD_LETTER = "DEAD_LETTER", "死信"


class EventDeliveryTargetType(models.TextChoices):
    LOCAL_CONSUMER = "LOCAL_CONSUMER", "本地消费"
    EXTERNAL_BROKER = "EXTERNAL_BROKER", "外部消息中间件"


class OutboxEvent(models.Model):
    """事件主表：业务事务内创建，状态由投递聚合推进。"""

    event_type = models.CharField(max_length=100, db_index=True)
    event_version = models.PositiveIntegerField(default=1)
    # 通用租户维度（不建 FK，避免 framework 反向依赖业务模型）；可为空（平台级事件）
    tenant_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    # 聚合维度：同一聚合的事件按 sequence 顺序投递（可选）
    aggregate_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    aggregate_sequence = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    payload = models.JSONField(default=dict)
    trace_id = models.CharField(max_length=100, null=True, blank=True)

    occurred_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)

    status = models.CharField(
        max_length=20, choices=OutboxEventStatus.choices,
        default=OutboxEventStatus.PENDING, db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "framework"
        ordering = ["-occurred_at"]
        indexes = [
            # worker 高频查询：按状态 + 可投递时间批量取单
            models.Index(fields=["status", "available_at"], name="outbox_st_avail_idx"),
        ]

    def __str__(self):
        return f"{self.event_type}:{self.status}"


class EventDelivery(models.Model):
    """投递目标表：事件 -> consumer 的投递状态（租约锁 / 重试 / 死信）。"""

    event = models.ForeignKey(
        OutboxEvent, related_name="deliveries", on_delete=models.CASCADE, db_index=True)
    target_name = models.CharField(max_length=100)
    target_type = models.CharField(
        max_length=20, choices=EventDeliveryTargetType.choices,
        default=EventDeliveryTargetType.LOCAL_CONSUMER, db_index=True,
    )
    consumer_module = models.CharField(max_length=100, null=True, blank=True)
    is_required = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20, choices=EventDeliveryStatus.choices,
        default=EventDeliveryStatus.PENDING, db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    # 租约锁：worker 认领后写 locked_by + locked_until；过期后其他 worker 可重新认领
    locked_by = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    locked_until = models.DateTimeField(null=True, blank=True)

    delivered_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        app_label = "framework"
        ordering = ["available_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "target_name"], name="uq_outbox_delivery_target"),
        ]
        indexes = [
            models.Index(fields=["status", "available_at"], name="deliv_st_avail_idx"),
            models.Index(fields=["locked_until"], name="deliv_lock_until_idx"),
        ]

    def __str__(self):
        return f"{self.event_id}:{self.target_name}:{self.status}"


class InboxReceipt(models.Model):
    """消费凭证表：consumer 成功消费 event 的幂等记录（at-most-once 兜底）。"""

    consumer_name = models.CharField(max_length=100)
    event = models.ForeignKey(
        OutboxEvent, related_name="receipts", on_delete=models.CASCADE, db_index=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "framework"
        constraints = [
            models.UniqueConstraint(
                fields=["consumer_name", "event"],
                name="uq_inbox_receipt_consumer_event"),
        ]

    def __str__(self):
        return f"{self.consumer_name}:{self.event_id}"
