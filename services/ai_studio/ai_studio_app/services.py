"""AI 创作工作室 - 业务服务层（身份解耦版）

核心机制：冻结-确认扣减（freeze-then-confirm）
1. 创建任务时先冻结预估额度（balance -= cost, frozen += cost）
2. 任务成功 -> 确认扣减（仅减 frozen）
3. 任务失败 -> 返还（frozen -= cost, balance += cost）
每笔变动均写入不可变流水账 QuotaTransaction。

身份说明：本服务的调用方（前端）携带主平台签发的 JWT，``user_id`` / ``username``
直接来自 token，因此所有函数以 ``user_id`` / ``username`` 入参，不依赖任何用户表。
"""
import base64
import random
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import UserQuota, QuotaTransaction, GenerationTask

# 注册（首次访问）赠送额度
SIGNUP_GIFT = getattr(settings, "AI_STUDIO_SIGNUP_GIFT", 50)
# 各分辨率单张成本
RES_COST = {"standard": 5, "hd": 8, "4k": 12}
# 视频相对图片的成本倍率（模拟按秒计费）
VIDEO_MULTIPLIER = 4

# 占位结果渐变色（mock 生成用，离线可预览）
_GRADIENTS = [
    ("#7c5cff", "#37c6ff"),
    ("#ff7eb3", "#ff758c"),
    ("#43e97b", "#38f9d7"),
    ("#fa709a", "#fee140"),
    ("#30cfd0", "#330867"),
    ("#a8edea", "#fed6e3"),
]


def compute_cost(kind: str, resolution: str, count: int) -> int:
    base = RES_COST.get(resolution, 5)
    if kind == "video":
        base *= VIDEO_MULTIPLIER
    return base * max(1, int(count))


def get_or_create_quota(user_id, username="") -> UserQuota:
    """按 user_id 取额度账户；不存在则创建并发放注册赠送额度。"""
    quota, created = UserQuota.objects.get_or_create(
        user_id=user_id, defaults={"username": username}
    )
    if created:
        _grant(quota, SIGNUP_GIFT, None, "注册赠送额度")
    elif username and quota.username != username:
        quota.username = username
        quota.save(update_fields=["username"])
    return quota


def _grant(quota: UserQuota, amount: int, task, remark: str) -> None:
    quota.balance += amount
    quota.total_granted += amount
    quota.save()
    QuotaTransaction.objects.create(
        user_id=quota.user_id, username=quota.username,
        tx_type="GRANT", amount=amount,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark=remark,
    )


def freeze(quota: UserQuota, amount: int, task) -> None:
    if quota.balance < amount:
        raise ValueError("额度不足")
    quota.balance -= amount
    quota.frozen += amount
    quota.save()
    QuotaTransaction.objects.create(
        user_id=quota.user_id, username=quota.username,
        tx_type="FREEZE", amount=amount,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark="任务预扣",
    )


def confirm(quota: UserQuota, task) -> None:
    quota.frozen = max(0, quota.frozen - task.cost)
    quota.save()
    QuotaTransaction.objects.create(
        user_id=quota.user_id, username=quota.username,
        tx_type="CONFIRM", amount=task.cost,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark="任务成功确认扣减",
    )


def refund(quota: UserQuota, task) -> None:
    quota.frozen = max(0, quota.frozen - task.cost)
    quota.balance += task.cost
    quota.save()
    QuotaTransaction.objects.create(
        user_id=quota.user_id, username=quota.username,
        tx_type="REFUND", amount=task.cost,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark="任务失败返还",
    )


def _make_placeholder(seed: int, label: str) -> str:
    c1, c2 = _GRADIENTS[seed % len(_GRADIENTS)]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{c1}"/>'
        f'<stop offset="100%" stop-color="{c2}"/>'
        '</linearGradient></defs>'
        '<rect width="600" height="600" fill="url(#g)"/>'
        '<text x="50%" y="50%" font-size="140" text-anchor="middle" '
        'dominant-baseline="middle">🛍️</text>'
        f'<text x="50%" y="92%" font-size="22" fill="rgba(255,255,255,.85)" '
        'text-anchor="middle">{label}</text></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return "data:image/svg+xml;base64," + encoded


def run_mock_generation(task_id: str) -> None:
    """mock 生成：模拟推理耗时并产出占位结果（离线可预览）。

    接入真实模型时，将本函数替换为调用图像/视频生成 API，
    并在完成后调用 confirm()；失败则调用 refund()。
    """
    task = GenerationTask.objects.get(id=task_id)
    task.status = "RUNNING"
    task.save(update_fields=["status"])

    time.sleep(random.uniform(1.2, 3.0))  # 模拟推理耗时

    results = [
        _make_placeholder(i, (task.prompt or "AI")[:10])
        for i in range(task.count)
    ]
    task.result_urls = results
    task.status = "SUCCESS"
    task.finished_at = timezone.now()
    task.save()

    quota = UserQuota.objects.get(user_id=task.user_id)
    confirm(quota, task)


@transaction.atomic
def create_generation_task(user_id, username, params: dict) -> GenerationTask:
    quota = get_or_create_quota(user_id, username)
    kind = params["kind"]
    resolution = params.get("resolution", "standard")
    count = int(params.get("count", 1))
    cost = compute_cost(kind, resolution, count)

    if quota.balance < cost:
        raise ValueError("额度不足")

    task = GenerationTask.objects.create(
        user_id=user_id,
        username=username,
        kind=kind,
        prompt=params.get("prompt", ""),
        ref_image=params.get("ref_image"),
        style=params.get("style", ""),
        size=params.get("size", "1:1"),
        resolution=resolution,
        count=count,
        cost=cost,
        status="PENDING",
    )
    freeze(quota, cost, task)

    # 默认同步 mock 执行（便于 demo 开箱即跑）；AI_STUDIO_SYNC=False 走 Celery 异步
    if getattr(settings, "AI_STUDIO_SYNC", True):
        run_mock_generation(task.id)
    else:
        from .tasks import generate_task

        res = generate_task.delay(task.id)
        task.celery_task_id = res.id
        task.save(update_fields=["celery_task_id"])

    task.refresh_from_db()
    return task
