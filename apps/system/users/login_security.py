"""登录安全：新设备登录站内信提醒（best-effort，绝不阻断登录）。

设计
----
- 复用 UserSession 历史记录做「新设备」判定：当前登录的 IP+UA 若从未出现在
  该用户的历史会话中，视为新设备 → 向收件箱发一条站内信提醒；
- 复用站内信服务 InAppNotificationService + MessageTemplate（code=login_new_device，
  由数据迁移播种），模板缺失/渲染失败回退默认文案，管理员可自定义；
- 全链路 try/except 吞异常：提醒失败不影响登录主流程（登录已提交会话，
  消息是附加产物，不参与事务）；
- 依赖方向：system.users 仅函数内延迟导入 business.alert_system（对齐
  core → ai_studio 的懒加载约定），模块导入零副作用。
"""
import re

from loguru import logger

# 模板 code：数据迁移播种，管理员可在后台自定义文案（占位符 {time}/{ip}/{device}）
TEMPLATE_CODE = "login_new_device"
DEFAULT_TITLE = "新设备登录提醒"
DEFAULT_CONTENT = (
    "您的账号于 {time} 在 {ip}（{device}）登录。如非本人操作，"
    "请立即修改密码并在「会话管理」中下线可疑设备。"
)


def _extract_device(ua: str) -> str:
    """从 User-Agent 提取可读设备标识（取括号内 OS/平台段，回退 UA 主标识）。"""
    ua = (ua or "").strip()
    if not ua:
        return "未知设备"
    m = re.search(r"\(([^)]+)\)", ua)
    device = m.group(1).strip() if m else (ua.split("/")[0].strip() or "未知设备")
    return (device or "未知设备")[:48]


def _is_new_device(user, session) -> bool:
    """当前会话的 IP+UA 是否在该用户历史会话中从未出现过。"""
    if not session.ip:
        return False  # 无 IP 信息（异常环境）不判定，静默跳过
    from system.users.models import UserSession

    return not UserSession.objects.filter(
        user=user,
        ip=session.ip,
        user_agent=session.user_agent,
    ).exclude(pk=session.pk).exists()


def maybe_notify_new_device_login(user, session, request=None) -> bool:
    """新设备登录则发站内信；返回是否已发送。任何异常都被吞掉（best-effort）。

    Args:
        user: 登录用户
        session: 刚创建的 UserSession（含 ip/user_agent/tenant）
        request: 可选，仅用于日志上下文
    """
    try:
        if session is None:
            return False
        if not _is_new_device(user, session):
            return False

        from django.utils import timezone as dj_tz

        from business.alert_system.services import InAppNotificationService

        time_str = dj_tz.localtime(session.created_at).strftime("%Y-%m-%d %H:%M")
        device = _extract_device(session.user_agent)
        tenant = session.tenant
        ctx = {"time": time_str, "ip": session.ip, "device": device}

        # 1) 优先模板（管理员可自定义文案）；模板缺失/渲染失败回退默认
        try:
            sent = InAppNotificationService.send_by_template(
                user, TEMPLATE_CODE, ctx,
                level="warning", tenant=tenant,
            )
            if sent is not None:
                return True
        except Exception:
            logger.exception("新设备登录模板渲染失败，回退默认文案 user={}", user.id)

        sent = InAppNotificationService.send_to_user(
            user, DEFAULT_TITLE,
            DEFAULT_CONTENT.format(**ctx),
            level="warning", tenant=tenant,
        )
        return sent is not None
    except Exception:
        logger.exception("新设备登录提醒发送失败 user={} ip={}", user.id, getattr(session, "ip", ""))
        return False
