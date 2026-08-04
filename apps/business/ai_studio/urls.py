"""AI 创作工作室路由（由主路由自动发现，前缀为 /api/ai_studio/）"""
from django.urls import path

from .views import (
    DemoLoginView, GenerateView, QuotaView, TaskListView, MeView,
    RechargeView, AdminGrantView, AdminUsersView,
    ChannelListView, ChannelDetailView, GrantView, MyChannelsView, AdminDashboardView,
    SsoTicketView, SsoBridgeView,
)

urlpatterns = [
    path('generate/', GenerateView.as_view(), name='ai-generate'),
    path('quota/', QuotaView.as_view(), name='ai-quota'),
    path('tasks/', TaskListView.as_view(), name='ai-tasks'),
    path('me/', MeView.as_view(), name='ai-me'),
    path('recharge/', RechargeView.as_view(), name='ai-recharge'),
    path('admin/grant/', AdminGrantView.as_view(), name='ai-admin-grant'),
    path('admin/users/', AdminUsersView.as_view(), name='ai-admin-users'),
    path('demo-login/', DemoLoginView.as_view(), name='ai-demo-login'),
    # 渠道/Agent 管理（管理员）
    path('channels/', ChannelListView.as_view(), name='ai-channels'),
    path('channels/<int:channel_id>/', ChannelDetailView.as_view(), name='ai-channel-detail'),
    # 用户-渠道授权（管理员控制点）
    path('grants/', GrantView.as_view(), name='ai-grants'),
    # 当前用户可用渠道（普通用户功能入口）
    path('my-channels/', MyChannelsView.as_view(), name='ai-my-channels'),
    # 管理员工作台概览
    path('admin/dashboard/', AdminDashboardView.as_view(), name='ai-admin-dashboard'),
    # SPA(JWT) -> Django 后台(Session) 单点登录桥接
    path('sso/ticket/', SsoTicketView.as_view(), name='ai-sso-ticket'),
    path('sso/bridge/', SsoBridgeView.as_view(), name='ai-sso-bridge'),
]
