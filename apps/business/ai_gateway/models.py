"""AI 网关 - 本地任务镜像。

主平台只作为入口：接收前端请求 → 经 RabbitMQ 把任务投递给 AI 服务 → 立即返回
task_id；前端再拿 task_id 连 AI 服务 WebSocket 主动获取结果。本表仅保存「已提交」
的镜像，用于主平台侧列表/审计，实时状态以 AI 服务为准（WebSocket 推送）。
"""
import uuid

from django.conf import settings
from django.db import models


class AiStudioTask(models.Model):
    """已提交到 AI 服务的生成任务镜像（主平台侧）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name="任务ID")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_gateway_tasks",
        verbose_name="提交用户",
    )
    status = models.CharField(max_length=10, default="PENDING", verbose_name="状态(提交时快照)")
    params = models.JSONField(default=dict, blank=True, verbose_name="请求参数")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI 网关任务"
        verbose_name_plural = "AI 网关任务"

    def __str__(self):
        return f"{self.id} {self.status}"
