"""AI 服务 WebSocket 消费者：生成结果的「主动查询-推送」通道。

前端建立连接后，本消费者按 task_id 周期性轮询本服务数据库中的任务状态，
并将最新状态/结果推送给客户端，直到任务进入终态（SUCCESS / FAILED）。

鉴权：连接 URL 的 query 中携带 `?token=<主平台签发的 JWT>`（与主平台共享
SIGNING_KEY 即可验签），并不依赖 Django session。token 的 user_id 声明
必须与任务归属的 user_id 一致，否则拒绝访问。
"""
import asyncio
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .models import GenerationTask

# 终态集合
_TERMINAL = {"SUCCESS", "FAILED"}
# 最大轮询次数（≈10 分钟，单次间隔 1s）
_MAX_POLLS = 600


def _auth_user_id(token: str):
    """用共享签名密钥验 JWT，返回 user_id；失败返回 None。"""
    if not token:
        return None
    try:
        validated = AccessToken(token)
        uid = validated.get("user_id")
        return str(uid) if uid is not None else None
    except (InvalidToken, TokenError, KeyError):
        return None


@database_sync_to_async
def _load_task(task_id, user_id):
    """返回任务对象；不存在返回 None；归属不符返回特殊标记 'FORBIDDEN'。"""
    try:
        task = GenerationTask.objects.get(id=task_id)
    except GenerationTask.DoesNotExist:
        return None
    if task.user_id != user_id:
        return "FORBIDDEN"
    return task


def _serialize(task: GenerationTask) -> dict:
    return {
        "task_id": str(task.id),
        "status": task.status,
        "kind": task.kind,
        "cost": task.cost,
        "result_urls": task.result_urls or [],
        "error_msg": task.error_msg,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


class AiStudioTaskConsumer(AsyncWebsocketConsumer):
    """按 task_id 主动查询并推送生成结果。"""

    async def connect(self):
        query = dict(
            x.split("=", 1) for x in self.scope["query_string"].decode().split("&") if x
        )
        self.user_id = _auth_user_id(query.get("token", ""))
        if not self.user_id:
            await self.close(code=4401)
            return

        self.task_id = self.scope["url_route"]["kwargs"].get("task_id")
        await self.accept()
        await self.send(
            json.dumps({"type": "connected", "task_id": str(self.task_id)})
        )

        await self._push_until_terminal()

    async def _push_until_terminal(self):
        # 任务可能尚未被 AI 服务创建（MQ 投递/消费存在时延），先短暂等待再判定
        not_found = 0
        for _ in range(_MAX_POLLS):
            row = await _load_task(self.task_id, self.user_id)
            if row is None:
                not_found += 1
                if not_found > 30:  # ~30s 内仍未创建，视为失败
                    await self.send(
                        json.dumps({"type": "error", "message": "任务不存在"})
                    )
                    await self.close()
                    return
                await asyncio.sleep(1)
                continue
            not_found = 0
            if row == "FORBIDDEN":
                await self.send(
                    json.dumps({"type": "error", "message": "无权访问该任务"})
                )
                await self.close(code=4403)
                return

            await self.send(
                json.dumps({"type": "progress", "data": _serialize(row)})
            )
            if row.status in _TERMINAL:
                break
            await asyncio.sleep(1)
        await self.close()

    async def receive(self, text_data):
        """支持客户端主动再次拉取（主动查询语义）。"""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if data.get("action") == "query":
            row = await _load_task(self.task_id, self.user_id)
            if isinstance(row, GenerationTask):
                await self.send(
                    json.dumps({"type": "progress", "data": _serialize(row)})
                )
