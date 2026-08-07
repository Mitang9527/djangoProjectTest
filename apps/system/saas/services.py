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
    def switch_tenant(user, tenant_id: Optional[str], session) -> Dict:
        """切换当前活跃租户, 返回结果。传 None 清除上下文"""
        if not tenant_id:
            session.pop("current_tenant_id", None)
            logger.info(f"用户 {user.username} 清除租户上下文")
            return {"msg": "已切换到全局视图", "tenant": None}

        is_super = user.is_superuser or getattr(user, "role", "user") == "admin"
        if is_super:
            tenant = Tenant.objects.filter(id=tenant_id).first()
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

        session["current_tenant_id"] = str(tenant.id)
        logger.info(f"用户 {user.username} 切换到租户 {tenant.name}")
        return {
            "msg": f"已切换到 {tenant.name}",
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
            },
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
