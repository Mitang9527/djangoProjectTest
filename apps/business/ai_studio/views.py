"""AI 创作工作室 - API 视图

路由（由主路由自动发现注册为 /api/ai_studio/）：
- POST generate/     创建生成任务（冻结额度 -> mock 生成 -> 确认扣减）
- GET  quota/        查询当前用户额度
- GET  tasks/        查询当前用户生成任务列表
- POST demo-login/   演示登录（默认禁用，需设置 ALLOW_DEMO_LOGIN=True；开发用，查找/创建用户并签发 JWT）
- POST sso/ticket/   签发短时 SSO 票据（前端持 JWT 调用）
- GET  sso/bridge/   凭票据建立 Django Session 并跳转后端页面（/saas/ 等）
"""
from django.conf import settings
from django.contrib.auth import get_user_model, login as django_login
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Sum, Count
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import escape
from django.views import View
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from loguru import logger

from .models import GenerationTask, RechargeOrder, ApiChannel, UserChannelGrant, UserQuota
from .serializers import (
    GenerationCreateSerializer,
    GenerationTaskSerializer,
    QuotaSerializer,
    RechargeSerializer,
    AdminGrantSerializer,
    ChannelSerializer,
    ChannelCreateSerializer,
    MyChannelSerializer,
    GrantSerializer,
    GrantWriteSerializer,
)
from .services import (
    create_generation_task, get_or_create_quota, recharge, admin_grant,
    can_use_channel, _is_admin,
)

User = get_user_model()


class IsPlatformAdmin(BasePermission):
    """平台管理员权限：超级管理员 或 拥有 admin 系统角色的用户"""

    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_staff:
            return True
        role = getattr(user, 'role', None)
        return bool(role and getattr(role, 'slug', None) == 'admin')


class GenerateView(APIView):
    permission_classes = [IsAuthenticated]
    # 同时支持 JSON 与 multipart：视频首帧需通过文件上传（first_frame）
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        user = request.user
        channel_id = request.data.get('channel_id')
        first_frame_file = request.FILES.get('first_frame')
        logger.info(
            f"[GENERATE] 收到请求 user={user.username} channel_id={channel_id} "
            f"kind={request.data.get('kind')} prompt={request.data.get('prompt')!r} "
            f"count={request.data.get('count')} has_first_frame_file={bool(first_frame_file)}"
        )

        ser = GenerationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # 上传的视频首帧：透传给 service，由模型 ImageField 落盘
        if first_frame_file:
            ser.validated_data['first_frame'] = first_frame_file

        channel = None
        if channel_id:
            channel = ApiChannel.objects.filter(id=channel_id).first()
            if not channel:
                logger.warning(
                    f"[GENERATE] 渠道不存在 user={user.username} channel_id={channel_id}"
                )
                return Response({"detail": "渠道/Agent 不存在"}, status=400)
            if not can_use_channel(user, channel):
                logger.warning(
                    f"[GENERATE] 无权使用渠道 user={user.username} channel={channel.name}"
                )
                return Response({"detail": "无权使用该渠道/Agent"}, status=403)

        try:
            idempotency_key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')
            task = create_generation_task(
                user, ser.validated_data, channel=channel,
                idempotency_key=idempotency_key,
            )
        except PermissionError as e:
            logger.warning(f"[GENERATE] 权限拦截 user={user.username} reason={e}")
            return Response({"detail": str(e)}, status=403)
        except ValueError as e:
            logger.warning(f"[GENERATE] 参数错误 user={user.username} reason={e}")
            return Response({"detail": str(e)}, status=400)

        quota = get_or_create_quota(user)
        logger.info(
            f"[GENERATE] 任务已创建 user={user.username} task_id={task.id} "
            f"channel={channel.name if channel else None} cost={task.cost} "
            f"frozen={quota.frozen} balance={quota.balance}"
        )
        # 失败原因统一收敛到 error 对象：{code, message}（替代旧的错误扁平字段 error_msg）
        error_block = None
        if task.status == 'FAILED':
            error_block = {
                'code': task.error_code or 'UNKNOWN',
                'message': task.error_msg or '生成失败，原因未知',
            }
        payload = {
            'task_id': task.id,
            'status': task.status,
            'cost': task.cost,
            'channel': channel.name if channel else None,
            'result_urls': task.result_urls,
            'error': error_block,
            'quota': {'balance': quota.balance, 'frozen': quota.frozen},
        }
        # 同步生成失败时，把失败原因透传给调用方（key 无效 / 配额不足 / 缺首帧等）。
        # 注意：统一响应渲染器在成功态会清空顶层 errors，因此失败原因放在
        # data.error 对象中，前端通过 data.status == 'FAILED' 判断并展示 data.error.message。
        if task.status == 'FAILED':
            logger.warning(
                f"[GENERATE] 同步生成失败 user={user.username} task_id={task.id} "
                f"code={task.error_code} reason={task.error_msg}"
            )
        return Response(payload)


class QuotaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        quota = get_or_create_quota(request.user)
        return Response(QuotaSerializer(quota).data)


class TaskListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tasks = GenerationTask.objects.filter(user=request.user)[:50]
        return Response({
            "tasks": GenerationTaskSerializer(tasks, many=True).data,
            "count": tasks.count(),
        })


class MeView(APIView):
    """当前登录用户身份信息（用于前端角色分流与刷新）"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        quota = get_or_create_quota(user)
        return Response({
            "id": user.id,
            "username": user.username,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "quota": {"balance": quota.balance, "frozen": quota.frozen},
        })


class RechargeView(APIView):
    """记账式充值（MVP：mock 支付，创建即支付，额度入账）"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        amount = request.data.get('amount')
        method = request.data.get('method', 'mock')
        logger.info(f"[RECHARGE] 充值请求 user={user.username} amount={amount} method={method}")

        ser = RechargeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            order = recharge(
                user,
                ser.validated_data['amount'],
                ser.validated_data.get('method', 'mock'),
            )
        except ValueError as e:
            logger.warning(f"[RECHARGE] 充值失败 user={user.username} reason={e}")
            return Response({"detail": str(e)}, status=400)

        quota = get_or_create_quota(user)
        logger.info(
            f"[RECHARGE] 充值成功 user={user.username} order_no={order.order_no} "
            f"quota_amount={order.quota_amount} balance={quota.balance} frozen={quota.frozen}"
        )
        return Response({
            "order_no": order.order_no,
            "quota_amount": order.quota_amount,
            "status": order.status,
            "balance": quota.balance,
            "frozen": quota.frozen,
        })


class AdminGrantView(APIView):
    """管理员发放/扣减用户额度（amount 为负即扣减）"""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        admin = request.user
        ser = AdminGrantSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        if data.get('user_id'):
            target = User.objects.filter(id=data['user_id']).first()
        elif data.get('username'):
            target = User.objects.filter(username=data['username']).first()
        else:
            return Response({"detail": "需提供 user_id 或 username"}, status=400)

        if not target:
            logger.warning(
                f"[GRANT] 目标用户不存在 operator={admin.username} "
                f"user_id={data.get('user_id')} username={data.get('username')}"
            )
            return Response({"detail": "目标用户不存在"}, status=404)

        logger.info(
            f"[GRANT] 额度调整 operator={admin.username} -> target={target.username} "
            f"amount={data['amount']} reason={data.get('reason', '')}"
        )
        try:
            quota = admin_grant(admin, target, data['amount'], data.get('reason', ''))
        except PermissionError as e:
            logger.warning(f"[GRANT] 权限拦截 operator={admin.username} reason={e}")
            return Response({"detail": str(e)}, status=403)
        except ValueError as e:
            logger.warning(f"[GRANT] 参数错误 operator={admin.username} reason={e}")
            return Response({"detail": str(e)}, status=400)

        logger.info(
            f"[GRANT] 调整完成 target={target.username} amount={data['amount']} "
            f"balance={quota.balance} frozen={quota.frozen}"
        )
        return Response({
            "user_id": target.id,
            "username": target.username,
            "amount": data["amount"],
            "balance": quota.balance,
            "frozen": quota.frozen,
        })


class AdminUsersView(APIView):
    """管理员查看用户额度列表（用于分配额度）"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        users = User.objects.all().select_related('ai_quota')[:200]
        data = []
        for u in users:
            q = getattr(u, 'ai_quota', None)
            data.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'is_staff': u.is_staff,
                'balance': q.balance if q else 0,
                'frozen': q.frozen if q else 0,
                'total_granted': q.total_granted if q else 0,
            })
        return Response({"users": data, "count": len(data)})


class ChannelListView(APIView):
    """渠道/Agent 管理（管理员）：列出全部 + 创建"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        channels = ApiChannel.objects.all()
        return Response({
            "channels": ChannelSerializer(channels, many=True).data,
            "count": channels.count(),
        })

    def post(self, request):
        ser = ChannelCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        channel = ser.save()
        return Response(ChannelSerializer(channel).data, status=201)


class ChannelDetailView(APIView):
    """渠道/Agent 详情：查看 / 修改 / 启停 / 删除（管理员）"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request, channel_id):
        channel = ApiChannel.objects.filter(id=channel_id).first()
        if not channel:
            return Response({"detail": "渠道不存在"}, status=404)
        return Response(ChannelSerializer(channel).data)

    def put(self, request, channel_id):
        channel = ApiChannel.objects.filter(id=channel_id).first()
        if not channel:
            return Response({"detail": "渠道不存在"}, status=404)
        ser = ChannelCreateSerializer(channel, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        channel = ser.save()
        return Response(ChannelSerializer(channel).data)

    def delete(self, request, channel_id):
        channel = ApiChannel.objects.filter(id=channel_id).first()
        if not channel:
            return Response({"detail": "渠道不存在"}, status=404)
        channel.delete()
        return Response({"detail": "已删除"}, status=204)


class GrantView(APIView):
    """用户-渠道授权管理（管理员）"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = UserChannelGrant.objects.select_related('user', 'channel').all()
        user_id = request.query_params.get('user_id')
        username = request.query_params.get('username')
        channel_id = request.query_params.get('channel_id')
        if user_id:
            qs = qs.filter(user_id=user_id)
        if username:
            qs = qs.filter(user__username=username)
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        return Response({
            "grants": GrantSerializer(qs[:200], many=True).data,
            "count": qs.count(),
        })

    def post(self, request):
        ser = GrantWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if data.get('user_id'):
            target = User.objects.filter(id=data['user_id']).first()
        elif data.get('username'):
            target = User.objects.filter(username=data['username']).first()
        else:
            return Response({"detail": "需提供 user_id 或 username"}, status=400)
        if not target:
            return Response({"detail": "目标用户不存在"}, status=404)
        channel = ApiChannel.objects.filter(id=data['channel_id']).first()
        if not channel:
            return Response({"detail": "渠道不存在"}, status=404)

        grant, _ = UserChannelGrant.objects.update_or_create(
            user=target, channel=channel,
            defaults={
                'enabled': data['enabled'],
                'per_user_quota': data.get('per_user_quota'),
                'granted_by': request.user,
            },
        )
        return Response(GrantSerializer(grant).data, status=201)

    def delete(self, request):
        user_id = request.query_params.get('user_id')
        username = request.query_params.get('username')
        channel_id = request.query_params.get('channel_id')
        if not channel_id:
            return Response({"detail": "需提供 channel_id"}, status=400)
        qs = UserChannelGrant.objects.all()
        if user_id:
            qs = qs.filter(user_id=user_id)
        elif username:
            qs = qs.filter(user__username=username)
        else:
            return Response({"detail": "需提供 user_id 或 username"}, status=400)
        deleted, _ = qs.filter(channel_id=channel_id).delete()
        return Response({"detail": "已撤销授权", "deleted": deleted}, status=200)


class MyChannelsView(APIView):
    """当前用户可使用的渠道/Agent（用户后台「功能入口」）"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _is_admin(request.user):
            channels = ApiChannel.objects.filter(is_active=True)
        else:
            grants = UserChannelGrant.objects.filter(
                user=request.user, enabled=True, channel__is_active=True,
            ).select_related('channel')
            channels = [g.channel for g in grants]
        return Response({
            "channels": MyChannelSerializer(channels, many=True).data,
            "count": len(channels),
        })


class AdminDashboardView(APIView):
    """管理员工作台概览（聚合数据）"""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        user_total = User.objects.count()
        user_active = User.objects.filter(is_active=True).count()
        quota_pool = UserQuota.objects.aggregate(
            balance=Sum('balance'), frozen=Sum('frozen'), granted=Sum('total_granted'))
        task_stats = dict(
            GenerationTask.objects.values_list('status').annotate(c=Count('id')))
        kind_stats = dict(
            GenerationTask.objects.values_list('kind').annotate(c=Count('id')))
        channel_total = ApiChannel.objects.count()
        channel_active = ApiChannel.objects.filter(is_active=True).count()
        recharge_paid = RechargeOrder.objects.filter(status='PAID').aggregate(
            s=Sum('quota_amount'))['s'] or 0
        return Response({
            "users": {"total": user_total, "active": user_active},
            "quota_pool": {
                "available": quota_pool["balance"] or 0,
                "frozen": quota_pool["frozen"] or 0,
                "total_granted": quota_pool["granted"] or 0,
            },
            "tasks": {
                "by_status": task_stats,
                "by_kind": kind_stats,
                "total": sum(task_stats.values()),
            },
            "channels": {"total": channel_total, "active": channel_active},
            "recharge_paid_total": recharge_paid,
        })


