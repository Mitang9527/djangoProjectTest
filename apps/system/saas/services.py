"""
SaaS 应用 - 业务逻辑层。

将 views.py 中的纯业务逻辑抽取到此处，包括:
- 仪表盘统计
- 租户切换
- 系统设置读写
- 备份/恢复
- 日志文件解析
- 权限分组
- 网关规则管理
- 缓存管理

views.py 只保留: 参数提取、权限声明、响应返回。
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.management import call_command
from django.db.models import Count, Q, Sum, QuerySet
from django.utils import timezone
from loguru import logger

from .models import (
    APILimitRule,
    Order,
    Permission,
    Role,
    Tenant,
    TenantConfig,
    TenantMember,
    GlobalConfig,
    FeatureFlag,
    ConfigHistory,
)


# ============================================================
# 仪表盘统计
# ============================================================

class DashboardService:
    """系统仪表盘数据服务"""

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """返回系统仪表盘统计数据"""
        total_tenants = Tenant.objects.count()
        active_tenants = Tenant.objects.filter(status="active").count()
        total_users = TenantMember.objects.filter(is_active=True).count()
        total_roles = Role.objects.filter(is_active=True).count()
        total_orders = Order.objects.count()
        revenue = (
            Order.objects.filter(status="paid").aggregate(total=Sum("amount"))["total"]
            or 0
        )
        recent_orders = list(
            Order.objects.order_by("-created_at")[:5].values(
                "id", "order_no", "amount", "status", "created_at"
            )
        )

        # 租户用户数排行
        top_tenants = list(
            Tenant.objects.filter(status="active")
            .annotate(member_count=Count("members", filter=Q(members__is_active=True)))
            .order_by("-member_count")[:5]
            .values("id", "name", "member_count")
        )

        # 最近 30 天新增用户趋势
        thirty_days_ago = datetime.now() - timedelta(days=30)
        daily_new_users = list(
            TenantMember.objects.filter(created_at__gte=thirty_days_ago)
            .extra(select={"day": "date(created_at)"})
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        return {
            "total_tenants": total_tenants,
            "active_tenants": active_tenants,
            "total_users": total_users,
            "total_roles": total_roles,
            "total_orders": total_orders,
            "revenue": float(revenue),
            "recent_orders": recent_orders,
            "top_tenants": top_tenants,
            "daily_new_users": [
                {"day": str(d["day"]), "count": d["count"]}
                for d in daily_new_users
            ],
        }


# ============================================================
# 租户切换
# ============================================================

class TenantService:
    """租户上下文管理服务"""

    @staticmethod
    def get_accessible_tenants(user) -> List[Dict]:
        """返回用户可访问的租户列表"""
        from .permissions import _is_super_admin

        if _is_super_admin(user):
            return list(
                Tenant.objects.filter(status="active").values("id", "name", "slug")
            )

        members = TenantMember.objects.filter(
            user=user, is_active=True
        ).select_related("tenant")
        return [
            {"id": str(m.tenant.id), "name": m.tenant.name, "slug": m.tenant.slug}
            for m in members
            if m.tenant.status == "active"
        ]

    @staticmethod
    def switch_tenant(user, tenant_id: Optional[str], session, request=None, access_token=None) -> Dict:
        """切换当前活跃租户并重签 JWT（对齐参考项目 /tenants/switch）。

        流程：
          1) 校验成员关系（超管特例保留：可直接切任意活跃租户）；
          2) 吊销当前 access 对应的旧会话（UserSession.revoked_at）→ 旧 token 立即失效；
          3) 重签 access+refresh，写入新 tenant_id claim；
          4) 为新 token 建会话记录（jti 绑定 user + 新租户）。

        Args:
            access_token: 当前请求的 validated token（SlidingJWT 认证下为
                          AccessToken，含 jti）；API Key / Session 认证下为 None，
                          则跳过旧会话吊销。
        Returns:
            {"msg", "tenant", "access", "refresh"}；无权限时 {"error"}
        """
        from django.utils import timezone as dj_timezone
        from rest_framework_simplejwt.tokens import RefreshToken
        from system.users.models import UserSession
        from system.users.serializers import create_user_session

        if not tenant_id:
            session.pop("current_tenant_id", None)
            logger.info(f"用户 {user.username} 清除租户上下文")
            return {"msg": "已切换到全局视图", "tenant": None}

        is_super = user.is_superuser or getattr(user, "role", "user") == "admin"
        if is_super:
            tenant = Tenant.objects.filter(id=tenant_id, status="active").first()
        else:
            member = (
                TenantMember.objects.filter(
                    user=user, tenant_id=tenant_id, is_active=True
                )
                .select_related("tenant")
                .first()
            )
            tenant = member.tenant if member else None

        if not tenant:
            return {"error": "无权限访问该租户"}

        # 1) 吊销旧会话（当前 access 的 jti）→ 旧 token 立即失效
        if access_token is not None:
            try:
                old_jti = access_token.payload.get("jti")
            except Exception:
                old_jti = None
            if old_jti:
                revoked = UserSession.objects.filter(
                    user=user, token_jti=old_jti, revoked_at__isnull=True
                ).update(revoked_at=dj_timezone.now())
                if revoked:
                    logger.info(
                        f"用户 {user.username} 切租户吊销旧会话 jti={old_jti}"
                    )

        # 2) 重签 token：携带新租户上下文 claim
        refresh = RefreshToken.for_user(user)
        refresh["tenant_id"] = str(tenant.id)
        refresh["username"] = user.username
        refresh["role_id"] = str(user.role.id) if user.role else None
        refresh["email"] = user.email
        # token_version 保持当前值：切租户只吊销当前会话，不注销其它设备。
        # 从 DB 读最新值（传入的 user 实例可能是过期对象，避免 claim 与 DB 不一致
        # 导致认证层 token_version 校验误杀新 token）。
        if hasattr(user, "token_version"):
            try:
                user.refresh_from_db(fields=["token_version"])
            except Exception:
                pass
            refresh["token_version"] = user.token_version or 0

        # 3) 新 token 建会话记录
        access = refresh.access_token
        create_user_session(user, access, tenant.id, request)

        # 4) 兼容旧逻辑：session 里写入当前租户（middleware 三源解析之一）
        session["current_tenant_id"] = str(tenant.id)
        logger.info(f"用户 {user.username} 切换到租户 {tenant.name}（Token 已重签）")
        return {
            "msg": f"已切换到 {tenant.name}",
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
            },
            "access": str(access),
            "refresh": str(refresh),
        }


# ============================================================
# 租户档案 / 生命周期 / 用量（效仿参考项目 operate_tenant_lifecycle）
# ============================================================

class TenantProfileService:
    """租户档案生命周期与用量统计服务（对齐参考项目 tenants.py）。"""

    # 生命周期状态 → Tenant.status 同步映射（参考项目 Tenant.is_active 布尔，
    # 本项目 Tenant.status 三态：active / suspended / cancelled）
    STATUS_BY_LIFECYCLE = {
        'trial': Tenant.Status.ACTIVE,
        'formal': Tenant.Status.ACTIVE,
        'frozen': Tenant.Status.SUSPENDED,
        'expired': Tenant.Status.SUSPENDED,
        'archived': Tenant.Status.CANCELLED,
    }

    # 允许的动作（对齐 TenantLifecycleAction 枚举）
    ACTION_CONVERT_TO_FORMAL = 'convert_to_formal'
    ACTION_RENEW = 'renew'
    ACTION_FREEZE = 'freeze'
    ACTION_UNFREEZE = 'unfreeze'
    ACTION_ARCHIVE = 'archive'
    ACTIONS = {
        ACTION_CONVERT_TO_FORMAL, ACTION_RENEW,
        ACTION_FREEZE, ACTION_UNFREEZE, ACTION_ARCHIVE,
    }

    @classmethod
    def get_or_create_profile(cls, tenant: Tenant) -> "TenantProfile":
        """幂等获取/创建租户档案（对齐参考项目 ensure_tenant_profile）。"""
        from .models import TenantProfile
        profile = getattr(tenant, 'profile', None)
        if profile is not None:
            return profile
        profile, _ = TenantProfile.objects.get_or_create(
            tenant=tenant,
            defaults={'lifecycle_status': 'formal', 'effective_at': timezone.now()},
        )
        return profile

    @classmethod
    def operate_lifecycle(
        cls,
        tenant: Tenant,
        action: str,
        service_expires_at=None,
        frozen_reason: Optional[str] = None,
        now=None,
    ) -> Dict:
        """执行租户生命周期动作（5 态状态机，对齐参考项目 operate_tenant_lifecycle）。

        Args:
            action: convert_to_formal / renew / freeze / unfreeze / archive
            service_expires_at: renew 时必填，须为未来时间
            frozen_reason: freeze 时必填
            now: 注入当前时间（测试用）

        Returns:
            成功 {"msg", "tenant": {...}}；失败 {"error": "..."}
        """
        from django.utils import timezone as dj_tz
        from .models import TenantProfile

        if action not in cls.ACTIONS:
            return {"error": f"无效的生命周期动作: {action}"}

        now = now or dj_tz.now()
        profile = cls.get_or_create_profile(tenant)
        current_status = profile.effective_status(now=now)
        profile_cls = TenantProfile.LifecycleStatus
        # 操作前捕获：tenant.status 未被本方法修改，作为「活跃 → 非活跃」转变基线
        # （参考项目用 tenant.is_active；本项目以 Tenant.status == active 等价）
        was_active = tenant.status == Tenant.Status.ACTIVE

        if action == cls.ACTION_CONVERT_TO_FORMAL:
            # 仅 trial → formal（参考：Only a trial tenant can become formal）
            if current_status != profile_cls.TRIAL:
                return {"error": "仅试用中的租户可转正式"}
            profile.lifecycle_status = profile_cls.FORMAL
            profile.effective_at = profile.effective_at or now

        elif action == cls.ACTION_RENEW:
            # 续费：到期时间必须在未来；过期恢复 formal；冻结且到期/试用已过 → before_freeze 置 formal
            if service_expires_at is None or service_expires_at <= now:
                return {"error": "续费到期时间必须晚于当前时间"}
            profile.service_expires_at = service_expires_at
            if current_status == profile_cls.EXPIRED:
                profile.lifecycle_status = profile_cls.FORMAL
            elif current_status == profile_cls.FROZEN:
                before = profile.lifecycle_status_before_freeze
                trial_over = (
                    before == profile_cls.TRIAL
                    and profile.trial_ends_at is not None
                    and profile.trial_ends_at <= now
                )
                if before == profile_cls.EXPIRED or trial_over:
                    profile.lifecycle_status_before_freeze = profile_cls.FORMAL
            elif current_status == profile_cls.ARCHIVED:
                return {"error": "已归档租户不可续费"}

        elif action == cls.ACTION_FREEZE:
            # 冻结：必须填原因；frozen/archived 拒绝；记录冻结前状态
            reason = (frozen_reason or "").strip()
            if not reason:
                return {"error": "冻结原因必填"}
            if current_status in (profile_cls.FROZEN, profile_cls.ARCHIVED):
                return {"error": "当前状态不可冻结"}
            profile.lifecycle_status_before_freeze = current_status
            profile.lifecycle_status = profile_cls.FROZEN
            profile.frozen_at = now
            profile.frozen_reason = reason

        elif action == cls.ACTION_UNFREEZE:
            # 解冻：仅 frozen；到期/试用已过须先续费
            if current_status != profile_cls.FROZEN:
                return {"error": "租户当前未冻结"}
            restored = profile.lifecycle_status_before_freeze or profile_cls.FORMAL
            trial_over = (
                restored == profile_cls.TRIAL
                and profile.trial_ends_at is not None
                and profile.trial_ends_at <= now
            )
            if (
                profile.service_expires_at is not None
                and profile.service_expires_at <= now
            ) or trial_over:
                return {"error": "租户已过期，解冻前须先续费"}
            profile.lifecycle_status = restored
            profile.lifecycle_status_before_freeze = None
            profile.frozen_at = None
            profile.frozen_reason = None

        elif action == cls.ACTION_ARCHIVE:
            # 归档：清冻结前状态
            profile.lifecycle_status = profile_cls.ARCHIVED
            profile.lifecycle_status_before_freeze = None

        # 同步 Tenant.status；活跃 → 非活跃转变时吊销该租户全部会话
        final_status = profile.effective_status(now=now)
        tenant.status = cls.STATUS_BY_LIFECYCLE.get(final_status, Tenant.Status.SUSPENDED)
        profile.save()
        tenant.save(update_fields=['status', 'updated_at'])
        if was_active and final_status not in (profile_cls.TRIAL, profile_cls.FORMAL):
            cls.revoke_tenant_sessions(tenant.id)

        action_names = {
            cls.ACTION_CONVERT_TO_FORMAL: "转正式",
            cls.ACTION_RENEW: "续费",
            cls.ACTION_FREEZE: "冻结",
            cls.ACTION_UNFREEZE: "解冻",
            cls.ACTION_ARCHIVE: "归档",
        }
        logger.info(
            f"租户 {tenant.name} 生命周期动作[{action_names.get(action, action)}] → "
            f"{final_status}（tenant.status={tenant.status}）"
        )
        return {
            "msg": f"已{action_names.get(action, action)}",
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "status": tenant.status,
                "lifecycle_status": final_status,
            },
        }

    @staticmethod
    def revoke_tenant_sessions(tenant_id: str) -> int:
        """吊销指定租户全部未失效会话（对齐参考项目 revoke_tenant_sessions）。"""
        from django.utils import timezone as dj_tz
        from system.users.models import UserSession
        return UserSession.objects.filter(
            tenant_id=tenant_id, revoked_at__isnull=True,
        ).update(revoked_at=dj_tz.now())

    @staticmethod
    def get_usage(tenant: Tenant) -> Dict:
        """租户用量统计（对齐参考项目 get_member_count + get_file_usage）。

        members: 活跃成员数（TenantMember.is_active=True）。
        file_assets / storage_bytes: 本项目尚无 FileAsset 资产登记表（参考项目有），
        暂以 0 占位；待资产登记模型落地后按 tenant_id 统计接入。
        """
        members = TenantMember.objects.filter(tenant=tenant, is_active=True).count()
        return {
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "members": members,
            "file_assets": 0,
            "storage_bytes": 0,
            "plan": (
                {
                    "id": str(tenant.plan.id),
                    "name": tenant.plan.name,
                    "slug": tenant.plan.slug,
                    "max_users": tenant.plan.max_users,
                    "max_storage_mb": tenant.plan.max_storage_mb,
                    "max_file_assets": tenant.plan.max_file_assets,
                }
                if tenant.plan_id
                else None
            ),
        }


# ============================================================
# 用户权限
# ============================================================

class PermissionService:
    """用户权限查询服务"""

    @staticmethod
    def get_user_permissions(user, tenant_id: Optional[str] = None) -> Dict:
        """返回用户在当前租户下的权限 slug 集合"""
        from .permissions import _is_super_admin
        from .permission_registry import ALL_PERMISSION_SLUGS

        if _is_super_admin(user):
            return {"is_super_admin": True, "permissions": ALL_PERMISSION_SLUGS}

        members = (
            TenantMember.objects.filter(user=user, is_active=True)
            .select_related("role")
            .prefetch_related("role__permissions")
        )
        if tenant_id:
            members = members.filter(tenant_id=tenant_id)

        slugs: set = set()
        for member in members:
            role = member.role
            if not role or not role.is_active:
                continue
            for perm in role.permissions.filter(is_active=True):
                slugs.add(perm.slug)

        # 用户直接关联的系统角色
        user_role = getattr(user, "role", None)
        if user_role and user_role.is_active:
            for perm in user_role.permissions.filter(is_active=True):
                slugs.add(perm.slug)

        return {"is_super_admin": False, "permissions": sorted(slugs)}

    @staticmethod
    def get_permissions_grouped() -> List[Dict]:
        """返回按模块分组的权限树"""
        from django.utils.translation import gettext_lazy as _

        module_names = {
            "system": _("系统管理"),
            "tenant": _("租户管理"),
            "user": _("用户管理"),
            "billing": _("计费管理"),
            "analytics": _("数据分析"),
        }

        permissions = Permission.objects.filter(is_active=True).order_by(
            "module", "slug"
        )

        modules_dict: Dict[str, Dict] = {}
        for perm in permissions:
            module = perm.module
            if module not in modules_dict:
                modules_dict[module] = {
                    "module": module,
                    "module_name": module_names.get(module, module),
                    "permissions": [],
                }
            modules_dict[module]["permissions"].append(
                {
                    "id": str(perm.id),
                    "name": perm.name,
                    "slug": perm.slug,
                    "description": perm.description,
                }
            )

        modules_list = sorted(modules_dict.values(), key=lambda x: x["module"])
        return modules_list


# ============================================================
# 系统设置
# ============================================================

SETTINGS_CATEGORIES = {
    "basic": {"title": "基本设置", "icon": "settings", "permission": "system.settings.basic", "category": "general"},
    "security": {"title": "安全设置", "icon": "shield", "permission": "system.settings.security", "category": "security"},
    "notification": {"title": "通知设置", "icon": "bell", "permission": "system.settings.notification", "category": "general"},
    "integration": {"title": "集成设置", "icon": "link", "permission": "system.settings.integration", "category": "integration"},
    "backup": {"title": "备份恢复", "icon": "archive", "permission": "system.settings.backup", "category": "general"},
}


class SettingsService:
    """租户系统设置服务"""

    @staticmethod
    def get_configs(tenant: Tenant, category: str = "general") -> Dict[str, str]:
        """读取某类别下所有配置项"""
        configs = TenantConfig.objects.filter(tenant=tenant, category=category)
        return {c.key: c.value for c in configs}

    @staticmethod
    def save_configs(tenant: Tenant, data: Dict[str, str], category: str = "general") -> List[Dict]:
        """批量保存配置项"""
        updated = []
        for key, value in data.items():
            config, created = TenantConfig.objects.update_or_create(
                tenant=tenant,
                key=key,
                defaults={
                    "value": str(value),
                    "category": category,
                    "description": f"{category} settings",
                },
            )
            updated.append({"key": key, "value": value, "created": created})
        logger.info(f"租户 {tenant.name} 更新了 {category} 设置")
        return updated


# ============================================================
# 备份/恢复
# ============================================================

class BackupService:
    """系统数据备份/恢复服务"""

    BACKUP_DIR = Path(settings.BASE_DIR) / "backups"

    @classmethod
    def create_backup(cls) -> Dict:
        """执行数据库备份 (dumpdata), 返回结果"""
        import sys

        cls.BACKUP_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.json"

        try:
            result = subprocess.run(
                [
                    sys.executable, "manage.py", "dumpdata",
                    "saas", "users", "--indent", "2",
                    "--output", str(cls.BACKUP_DIR / filename),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(settings.BASE_DIR),
            )
            if result.returncode == 0:
                logger.info(f"系统备份成功: {filename}")
                return {"status": "ok", "filename": filename, "msg": "备份成功"}
            else:
                logger.error(f"系统备份失败: {result.stderr}")
                return {"status": "error", "msg": result.stderr[:500]}
        except subprocess.TimeoutExpired:
            return {"status": "error", "msg": "备份超时"}
        except Exception as e:
            return {"status": "error", "msg": str(e)}

    @classmethod
    def list_backups(cls) -> List[Dict]:
        """列出所有备份文件"""
        if not cls.BACKUP_DIR.exists():
            return []

        backups = []
        for f in sorted(cls.BACKUP_DIR.glob("*.json"), reverse=True):
            stat = f.stat()
            backups.append({
                "filename": f.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return backups


# ============================================================
# 日志文件解析
# ============================================================

LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LOG_LINE_RE = re.compile(
    r"^(?P<datetime>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*"
    r"(?P<level>TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|"
)


class LogService:
    """系统日志读取/解析服务"""

    LOG_DIR = Path(settings.BASE_DIR) / "logs"

    @classmethod
    def find_latest_log(cls) -> Optional[Path]:
        """找到最新的日志文件"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_log = cls.LOG_DIR / f"{today_str}.log"
        if today_log.exists():
            return today_log

        log_files = sorted(cls.LOG_DIR.glob("*.log"), reverse=True)
        return log_files[0] if log_files else None

    @classmethod
    def parse_log(
        cls,
        filepath: Path,
        level_filter: Optional[List[str]] = None,
        search: str = "",
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        """解析 .log 文件，返回分页结果"""
        entries = []
        if not filepath.exists():
            return {"entries": [], "total": 0, "page": page, "page_size": page_size}

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        i = 0
        while i < len(lines):
            line = lines[i]
            m = LOG_LINE_RE.match(line)
            if m:
                ts = m.group("datetime")
                level = m.group("level")

                body_lines = [line[m.end():].strip()]
                i += 1
                while i < len(lines):
                    if LOG_LINE_RE.match(lines[i]):
                        break
                    body_lines.append(lines[i].rstrip("\n"))
                    i += 1

                if level_filter and level not in level_filter:
                    continue
                if date_from and ts < date_from:
                    continue
                if date_to and ts > date_to:
                    continue
                if search and search.lower() not in " ".join(body_lines).lower():
                    continue

                entries.append({
                    "datetime": ts,
                    "level": level,
                    "message": "\n".join(body_lines)[:2000],
                })
            else:
                i += 1

        total = len(entries)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "entries": entries[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }


# ============================================================
# 网关规则管理
# ============================================================

class GatewayService:
    """API 网关规则管理服务"""

    @staticmethod
    def get_dashboard() -> Dict:
        """网关仪表盘数据"""
        rules = APILimitRule.objects.all()
        active_count = rules.filter(is_active=True).count()

        type_stats = {}
        for rt in APILimitRule.RuleType:
            type_stats[rt.value] = rules.filter(
                is_active=True, throttle_type=rt.value
            ).count()

        from framework.gateway.throttle import DEFAULT_THROTTLE_RATES

        return {
            "total_rules": rules.count(),
            "active_rules": active_count,
            "inactive_rules": rules.count() - active_count,
            "type_stats": type_stats,
            "global_defaults": DEFAULT_THROTTLE_RATES,
            "throttle_types": [
                {"id": "ip", "name": "IP 限流", "desc": "按客户端 IP 地址限制"},
                {"id": "user", "name": "用户限流", "desc": "按认证用户限制"},
                {"id": "tenant", "name": "租户限流", "desc": "按租户限制"},
                {"id": "endpoint", "name": "端点限流", "desc": "按 API 路由限制"},
            ],
        }

    @staticmethod
    def list_rules() -> List[Dict]:
        """列出所有限流规则"""
        rules = APILimitRule.objects.all().order_by("priority", "-created_at")
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "url_pattern": r.url_pattern,
                "throttle_type": r.throttle_type,
                "throttle_type_display": r.get_throttle_type_display(),
                "rate": r.rate,
                "is_active": r.is_active,
                "use_regex": r.use_regex,
                "priority": r.priority,
                "description": r.description,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
                "updated_at": r.updated_at.strftime("%Y-%m-%d %H:%M"),
            }
            for r in rules
        ]

    @staticmethod
    def create_rule(data: Dict) -> Dict:
        """创建限流规则, 返回 (rule, error)"""
        name = data.get("name", "").strip()
        url_pattern = data.get("url_pattern", "").strip()
        throttle_type = data.get("throttle_type", "ip")
        rate = data.get("rate", "100/h")
        is_active = data.get("is_active", True)
        use_regex = data.get("use_regex", False)
        priority = data.get("priority", 0)
        description = data.get("description", "")

        if not name:
            return {"error": "规则名称不能为空"}
        if not url_pattern:
            return {"error": "URL 模式不能为空"}

        valid_types = [t[0] for t in APILimitRule.RuleType.choices]
        if throttle_type not in valid_types:
            return {"error": f"无效的限流类型, 可选: {', '.join(valid_types)}"}

        if not re.match(r"^\d+/(s|m|h|d)$", rate):
            return {"error": "速率格式无效, 示例: 100/h"}

        rule = APILimitRule.objects.create(
            name=name,
            url_pattern=url_pattern,
            throttle_type=throttle_type,
            rate=rate,
            is_active=is_active,
            use_regex=use_regex,
            priority=priority,
            description=description,
        )

        return {
            "rule": {
                "id": str(rule.id),
                "name": rule.name,
                "url_pattern": rule.url_pattern,
                "throttle_type": rule.throttle_type,
                "rate": rule.rate,
            }
        }

    @staticmethod
    def update_rule(rule_id: str, data: Dict) -> Optional[Dict]:
        """更新限流规则, 返回错误或 None"""
        try:
            rule = APILimitRule.objects.get(id=rule_id)
        except APILimitRule.DoesNotExist:
            return {"error": "规则不存在"}

        for field in ["name", "url_pattern", "throttle_type", "rate", "description"]:
            val = data.get(field)
            if val is not None:
                setattr(rule, field, val)

        for field in ["is_active", "use_regex"]:
            val = data.get(field)
            if val is not None:
                setattr(rule, field, bool(val))

        if "priority" in data:
            rule.priority = int(data["priority"])

        rule.save()
        return None  # success

    @staticmethod
    def delete_rule(rule_id: str) -> Optional[Dict]:
        """删除限流规则"""
        try:
            rule = APILimitRule.objects.get(id=rule_id)
            rule.delete()
            return None
        except APILimitRule.DoesNotExist:
            return {"error": "规则不存在"}

    @staticmethod
    def toggle_rule(rule_id: str) -> Dict:
        """切换规则启用/禁用"""
        try:
            rule = APILimitRule.objects.get(id=rule_id)
            rule.is_active = not rule.is_active
            rule.save()
            return {
                "id": str(rule.id),
                "is_active": rule.is_active,
                "msg": f"规则已{'启用' if rule.is_active else '禁用'}",
            }
        except APILimitRule.DoesNotExist:
            return {"error": "规则不存在"}


# ============================================================
# 缓存管理
# ============================================================

class CacheService:
    """缓存管理服务"""

    VALID_TAGS = {"dashboard", "permissions", "tenant", "export", "gateway", "system"}

    @staticmethod
    def get_stats() -> Dict:
        """获取缓存命中率统计"""
        from framework.cache import CacheStats
        return CacheStats.snapshot()

    @staticmethod
    def invalidate_by_tag(tag: str) -> Dict:
        """按标签批量失效缓存"""
        if tag not in CacheService.VALID_TAGS:
            return {"error": f"无效的 tag, 支持: {', '.join(sorted(CacheService.VALID_TAGS))}"}

        from framework.cache import invalidate_by_tag as _invalidate
        count = _invalidate(tag)
        return {"msg": f"已失效 {count} 个缓存键", "count": count}

    @staticmethod
    def warmup_all() -> Dict:
        """执行所有已注册的预热函数"""
        from framework.cache import warmup_all as _warmup
        results = _warmup(verbose=True)
        success_count = sum(1 for v in results.values() if v)
        return {
            "msg": f"预热完成: {success_count}/{len(results)} 成功",
            "results": results,
        }

    @staticmethod
    def reset_stats() -> Dict:
        """重置缓存命中率统计"""
        from framework.cache import CacheStats
        CacheStats.reset()
        return {"msg": "统计已重置"}


# ============================================================
# 配置中心服务
# ============================================================

class ConfigCenterService:
    """
    配置中心服务类 - 提供配置的增删改查、热加载和缓存管理
    """
    
    _cache: Dict[str, Any] = {}
    _cache_updated_at: Optional[datetime] = None
    CACHE_TTL = 60  # 秒
    
    @classmethod
    def _get_cache_key(cls, key: str) -> str:
        return f"config:{key}"
    
    @classmethod
    def _clear_cache(cls, key: Optional[str] = None) -> None:
        """清除缓存（单个或全部）"""
        if key:
            cls._cache.pop(cls._get_cache_key(key), None)
        else:
            cls._cache.clear()
        cls._cache_updated_at = datetime.now()
    
    @classmethod
    def get_config(cls, key: str, default: Any = None) -> Any:
        """
        获取配置值 - 支持热加载和类型自动转换
        
        Args:
            key: 配置键
            default: 默认值
            
        Returns:
            解析后的配置值
        """
        cache_key = cls._get_cache_key(key)
        
        # 检查缓存是否需要刷新
        if cls._cache_updated_at:
            elapsed = (datetime.now() - cls._cache_updated_at).total_seconds()
            if elapsed > cls.CACHE_TTL:
                cls._clear_cache()
        
        # 从缓存获取
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        # 从数据库获取
        try:
            config = GlobalConfig.objects.filter(key=key, is_active=True).first()
            if config:
                value = config.parsed_value
                cls._cache[cache_key] = value
                return value
        except Exception as e:
            logger.error(f"获取配置 {key} 失败: {e}")
        
        return default
    
    @classmethod
    def get_all_configs(cls, category: Optional[str] = None) -> Dict[str, Any]:
        """
        获取所有配置（或按分类获取）
        
        Args:
            category: 配置分类，可选
            
        Returns:
            配置字典 {key: parsed_value}
        """
        queryset = GlobalConfig.objects.filter(is_active=True)
        if category:
            queryset = queryset.filter(category=category)
        
        configs = {}
        for config in queryset:
            configs[config.key] = config.parsed_value
        
        return configs
    
    @classmethod
    def get_public_configs(cls) -> Dict[str, Any]:
        """
        获取公开配置（供前端使用）
        
        Returns:
            公开配置字典
        """
        queryset = GlobalConfig.objects.filter(is_active=True, is_public=True)
        return {c.key: c.parsed_value for c in queryset}
    
    @classmethod
    def set_config(cls, key: str, value: Any, user=None, 
                   name: Optional[str] = None, description: str = "",
                   category: str = "system", config_type: str = "string") -> Dict:
        """
        设置配置（新增或更新）
        
        Args:
            key: 配置键
            value: 配置值
            user: 操作用户
            name: 配置名称（新增时必填）
            description: 配置描述
            category: 分类
            config_type: 类型
            
        Returns:
            操作结果
        """
        # 转换值为字符串存储
        if config_type == "json":
            import json
            value_str = json.dumps(value, ensure_ascii=False)
        elif config_type == "boolean":
            value_str = str(value).lower()
        else:
            value_str = str(value)
        
        old_value = None
        config = GlobalConfig.objects.filter(key=key).first()
        
        if config:
            # 更新
            old_value = config.value
            config.value = value_str
            config.category = category
            if description:
                config.description = description
            if config_type:
                config.config_type = config_type
            if user:
                config.updated_by = user
            config.save()
            operation = "UPDATE"
        else:
            # 新增
            if not name:
                return {"error": "新增配置时 name 不能为空"}
            config = GlobalConfig.objects.create(
                key=key,
                name=name,
                value=value_str,
                description=description,
                category=category,
                config_type=config_type,
                created_by=user,
                updated_by=user,
            )
            operation = "CREATE"
        
        # 记录历史
        cls._record_history(key, "global_config", operation, old_value, value_str, user)
        
        # 清除缓存
        cls._clear_cache(key)
        
        return {"status": "ok", "config": config}
    
    @classmethod
    def delete_config(cls, key: str, user=None) -> Dict:
        """
        删除配置
        
        Args:
            key: 配置键
            user: 操作用户
            
        Returns:
            操作结果
        """
        try:
            config = GlobalConfig.objects.get(key=key)
            old_value = config.value
            config.delete()
            
            # 记录历史
            cls._record_history(key, "global_config", "DELETE", old_value, None, user)
            
            # 清除缓存
            cls._clear_cache(key)
            
            return {"status": "ok"}
        except GlobalConfig.DoesNotExist:
            return {"error": "配置不存在"}
    
    @classmethod
    def reload_configs(cls) -> Dict:
        """
        强制重新加载所有配置
        
        Returns:
            操作结果
        """
        cls._clear_cache()
        return {"status": "ok", "msg": "配置已刷新"}
    
    @staticmethod
    def _record_history(config_key: str, config_type: str, operation: str,
                       old_value: Optional[str], new_value: Optional[str], 
                       user=None) -> None:
        """记录配置变更历史"""
        try:
            ConfigHistory.objects.create(
                config_key=config_key,
                config_type=config_type,
                operation=operation.lower(),
                old_value=old_value,
                new_value=new_value,
                operator=user,
            )
        except Exception as e:
            logger.error(f"记录配置历史失败: {e}")


# ============================================================
# 特性开关/灰度发布服务
# ============================================================

class FeatureFlagService:
    """
    特性开关/灰度发布服务类
    """
    
    @staticmethod
    def is_enabled(feature_key: str, user=None, tenant=None) -> bool:
        """
        判断特性是否对当前用户/租户启用
        
        Args:
            feature_key: 特性键
            user: 用户对象
            tenant: 租户对象
            
        Returns:
            bool: 是否启用
        """
        try:
            feature = FeatureFlag.objects.filter(key=feature_key).first()
            if not feature:
                return False
            
            if user:
                return feature.is_enabled_for_user(user, tenant)
            
            # 如果没有用户上下文，只检查 ALL 策略
            return (feature.status == FeatureFlag.Status.ACTIVE and 
                   feature.rollout_strategy == FeatureFlag.RolloutStrategy.ALL)
        except Exception as e:
            logger.error(f"检查特性开关 {feature_key} 失败: {e}")
            return False
    
    @staticmethod
    def get_user_features(user, tenant=None) -> Dict[str, bool]:
        """
        获取用户所有可用的特性开关
        
        Args:
            user: 用户对象
            tenant: 租户对象
            
        Returns:
            Dict: {feature_key: is_enabled}
        """
        features = FeatureFlag.objects.filter(status=FeatureFlag.Status.ACTIVE)
        result = {}
        for feature in features:
            result[feature.key] = feature.is_enabled_for_user(user, tenant)
        return result
    
    @staticmethod
    def update_feature_flag(feature_id: str, data: Dict, user=None) -> Dict:
        """
        更新特性开关
        
        Args:
            feature_id: 特性ID
            data: 更新数据
            user: 操作用户
            
        Returns:
            操作结果
        """
        try:
            feature = FeatureFlag.objects.get(id=feature_id)
            old_value = str({
                "status": feature.status,
                "rollout_strategy": feature.rollout_strategy,
                "rollout_percentage": feature.rollout_percentage,
            })
            
            # 更新字段
            for field in ["name", "description", "status", "rollout_strategy", 
                         "rollout_percentage", "starts_at", "ends_at", "metadata"]:
                if field in data:
                    setattr(feature, field, data[field])
            
            if user:
                feature.updated_by = user
            
            feature.save()
            
            # 记录历史
            new_value = str({
                "status": feature.status,
                "rollout_strategy": feature.rollout_strategy,
                "rollout_percentage": feature.rollout_percentage,
            })
            ConfigCenterService._record_history(
                feature.key, "feature_flag", "UPDATE", old_value, new_value, user
            )
            
            return {"status": "ok", "feature": feature}
        except FeatureFlag.DoesNotExist:
            return {"error": "特性开关不存在"}
    
    @staticmethod
    def toggle_status(feature_id: str, user=None) -> Dict:
        """
        切换特性开关状态
        
        Args:
            feature_id: 特性ID
            user: 操作用户
            
        Returns:
            操作结果
        """
        try:
            feature = FeatureFlag.objects.get(id=feature_id)
            old_status = feature.status
            
            if feature.status == FeatureFlag.Status.ACTIVE:
                feature.status = FeatureFlag.Status.PAUSED
            else:
                feature.status = FeatureFlag.Status.ACTIVE
            
            if user:
                feature.updated_by = user
            
            feature.save()
            
            # 记录历史
            ConfigCenterService._record_history(
                feature.key, "feature_flag", "UPDATE", 
                str(old_status), str(feature.status), user
            )
            
            return {
                "status": "ok", 
                "is_active": feature.status == FeatureFlag.Status.ACTIVE
            }
        except FeatureFlag.DoesNotExist:
            return {"error": "特性开关不存在"}
