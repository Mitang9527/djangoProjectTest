"""
领域事件 Outbox 模型。

Transaction Outbox 模式：业务在事务内写入 ``OutboxEvent``（PENDING），由 worker
异步取出并投递到通知 / 审计 / 索引等下游，保证「业务成功则事件必不丢」。

注意：本模型 ``app_label='framework'``，需在 settings.INSTALLED_APPS 加入
``'framework'``（或改用所属业务 app 的 app_label）并生成迁移后方可启用 DB 落盘；
未启用时 events.publish 自动降级为内存直发（见 publisher）。
"""
from django.db import models


class OutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "待投递"
        SENT = "SENT", "已投递"
        FAILED = "FAILED", "失败"

    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "framework"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type}:{self.status}"
