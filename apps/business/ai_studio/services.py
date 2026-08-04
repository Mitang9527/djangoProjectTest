"""AI 创作工作室 - 业务服务层

核心机制：冻结-确认扣减（freeze-then-confirm）
1. 创建任务时先冻结预估额度（balance -= cost, frozen += cost）
2. 任务成功 -> 确认扣减（仅减 frozen）
3. 任务失败 -> 返还（frozen -= cost, balance += cost）
每笔变动均写入不可变流水账 QuotaTransaction。
"""
import base64
import random
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    UserQuota, QuotaTransaction, GenerationTask, RechargeOrder,
    ApiChannel, UserChannelGrant,
)

# 注册赠送额度
SIGNUP_GIFT = 50
# 各分辨率单张成本
RES_COST = {'standard': 5, 'hd': 8, '4k': 12}
# 视频相对图片的成本倍率（模拟按秒计费）
VIDEO_MULTIPLIER = 4

# 占位结果渐变色（mock 生成用，离线可预览）
_GRADIENTS = [
    ('#7c5cff', '#37c6ff'),
    ('#ff7eb3', '#ff758c'),
    ('#43e97b', '#38f9d7'),
    ('#fa709a', '#fee140'),
    ('#30cfd0', '#330867'),
    ('#a8edea', '#fed6e3'),
]


def compute_cost(kind: str, resolution: str, count: int) -> int:
    base = RES_COST.get(resolution, 5)
    if kind == 'video':
        base *= VIDEO_MULTIPLIER
    return base * max(1, int(count))


def get_or_create_quota(user) -> UserQuota:
    quota, created = UserQuota.objects.get_or_create(user=user)
    if created and not quota.signup_granted:
        _grant(quota, SIGNUP_GIFT, None, '注册赠送额度', 'GRANT')
        quota.signup_granted = True
        quota.save(update_fields=['signup_granted'])
    return quota


def _grant(quota: UserQuota, amount: int, task, remark: str, tx_type: str = 'GRANT') -> None:
    quota.balance += amount
    quota.total_granted += amount
    quota.save()
    QuotaTransaction.objects.create(
        user=quota.user, tx_type=tx_type, amount=amount,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark=remark,
    )


def freeze(quota: UserQuota, amount: int, task) -> None:
    if quota.balance < amount:
        raise ValueError('额度不足')
    quota.balance -= amount
    quota.frozen += amount
    quota.save()
    QuotaTransaction.objects.create(
        user=quota.user, tx_type='FREEZE', amount=amount,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark='任务预扣',
    )


def confirm(quota: UserQuota, task) -> None:
    quota.frozen = max(0, quota.frozen - task.cost)
    quota.save()
    # 累计渠道专属消耗（管理员据此控制单用户在某渠道的总额度）
    ch = getattr(task, 'channel', None)
    if ch:
        grant = UserChannelGrant.objects.filter(user=task.user, channel=ch).first()
        if grant:
            grant.used_quota = (grant.used_quota or 0) + task.cost
            grant.save(update_fields=['used_quota'])
    QuotaTransaction.objects.create(
        user=quota.user, tx_type='CONFIRM', amount=task.cost,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark='任务成功确认扣减',
    )


def refund(quota: UserQuota, task) -> None:
    quota.frozen = max(0, quota.frozen - task.cost)
    quota.balance += task.cost
    quota.save()
    QuotaTransaction.objects.create(
        user=quota.user, tx_type='REFUND', amount=task.cost,
        balance_after=quota.balance, frozen_after=quota.frozen,
        task=task, remark='任务失败返还',
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
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return 'data:image/svg+xml;base64,' + encoded


def run_mock_generation(task_id: str) -> None:
    """mock 生成：模拟推理耗时并产出占位结果（离线可预览）。

    接入真实模型时，将本函数替换为调用图像/视频生成 API，
    并在完成后调用 confirm()；失败则调用 refund()。
    """
    task = GenerationTask.objects.get(id=task_id)
    task.status = 'RUNNING'
    task.save(update_fields=['status'])

    time.sleep(random.uniform(1.2, 3.0))  # 模拟推理耗时

    results = [
        _make_placeholder(i, (task.prompt or 'AI')[:10])
        for i in range(task.count)
    ]
    task.result_urls = results
    task.status = 'SUCCESS'
    task.finished_at = timezone.now()
    task.save()

    quota = UserQuota.objects.get(user=task.user)
    confirm(quota, task)


@transaction.atomic
def create_generation_task(user, params: dict, channel=None) -> GenerationTask:
    quota = get_or_create_quota(user)
    kind = params['kind']
    resolution = params.get('resolution', 'standard')
    count = int(params.get('count', 1))

    if channel is not None:
        if not can_use_channel(user, channel):
            raise PermissionError('无权使用该渠道/Agent')
        # 渠道单价计价：cost_per_call(每张) × 数量；若未设单价则回退分辨率计价
        cost = (channel.cost_per_call or 0) * max(1, count)
        if cost <= 0:
            cost = compute_cost(kind, resolution, count)
    else:
        cost = compute_cost(kind, resolution, count)

    if quota.balance < cost:
        raise ValueError('额度不足')

    task = GenerationTask.objects.create(
        user=user,
        kind=kind,
        prompt=params.get('prompt', ''),
        ref_image=params.get('ref_image'),
        style=params.get('style', ''),
        size=params.get('size', '1:1'),
        resolution=resolution,
        count=count,
        cost=cost,
        channel=channel,
        status='PENDING',
    )
    freeze(quota, cost, task)

    # 默认同步 mock 执行（便于 demo 开箱即跑）；配置 AI_STUDIO_SYNC=False 走 Celery 异步
    if getattr(settings, 'AI_STUDIO_SYNC', True):
        run_mock_generation(task.id)
    else:
        from .tasks import generate_task
        res = generate_task.delay(task.id)
        task.celery_task_id = res.id
        task.save(update_fields=['celery_task_id'])

    task.refresh_from_db()
    return task


def _gen_order_no() -> str:
    return 'RC' + time.strftime('%Y%m%d%H%M%S') + uuid.uuid4().hex[:6].upper()


def _is_admin(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_staff:
        return True
    role = getattr(user, 'role', None)
    return bool(role and getattr(role, 'slug', None) == 'admin')


def can_use_channel(user, channel) -> bool:
    """判断用户是否可使用某渠道：

    - 渠道必须开放(is_active)
    - 管理员不受授权限制
    - 普通用户需存在 enabled 授权，且（未设 per_user_quota 或累计消耗未超限）
    """
    if not channel or not getattr(channel, 'is_active', False):
        return False
    if _is_admin(user):
        return True
    grant = UserChannelGrant.objects.filter(user=user, channel=channel).first()
    if not grant or not grant.enabled:
        return False
    if grant.per_user_quota and (grant.used_quota or 0) >= grant.per_user_quota:
        return False
    return True


@transaction.atomic
def recharge(user, amount: int, method: str = 'mock', remark: str = '') -> RechargeOrder:
    """记账式充值（MVP：mock 支付，创建即支付）。"""
    amount = int(amount)
    if amount <= 0:
        raise ValueError('充值额度必须为正数')
    quota = get_or_create_quota(user)
    order = RechargeOrder.objects.create(
        user=user,
        quota_amount=amount,
        status='PAID',
        method=method,
        order_no=_gen_order_no(),
        paid_at=timezone.now(),
        remark=remark or '用户充值',
    )
    _grant(quota, amount, None, f'充值+{amount} (单号{order.order_no})', 'RECHARGE')
    return order


@transaction.atomic
def admin_grant(operator, target_user, amount: int, reason: str = '') -> UserQuota:
    """管理员发放/扣减用户额度（amount 为负即扣减）。"""
    if not _is_admin(operator):
        raise PermissionError('无管理员权限')
    amount = int(amount)
    if amount == 0:
        raise ValueError('额度变动不能为 0')
    quota = get_or_create_quota(target_user)
    tx_type = 'ADMIN_GRANT' if amount > 0 else 'ADMIN_DEDUCT'
    _grant(quota, amount, None, f'管理员操作: {reason}', tx_type)
    return quota
