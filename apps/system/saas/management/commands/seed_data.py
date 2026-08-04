"""
管理命令：初始化种子数据
用法：
    python manage.py seed_data
    python manage.py seed_data --reset   # 删除已有种子数据后重新创建
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from loguru import logger

# ---------------------------------------------------------------------------
# 种子数据定义
# ---------------------------------------------------------------------------

SEED_PLANS = [
    {
        "slug": "free",
        "name": "免费套餐",
        "description": "基础功能，适合个人和小团队体验试用",
        "price": Decimal("0.00"),
        "price_yearly": None,
        "max_users": 5,
        "max_storage_mb": 128,
        "is_featured": False,
        "sort_order": 1,
    },
    {
        "slug": "starter",
        "name": "入门版",
        "description": "增强功能，适合初创团队和成长型业务",
        "price": Decimal("99.00"),
        "price_yearly": Decimal("990.00"),
        "max_users": 10,
        "max_storage_mb": 512,
        "is_featured": True,
        "sort_order": 2,
    },
    {
        "slug": "pro",
        "name": "专业版",
        "description": "高级功能，适合中等规模公司和专业需求",
        "price": Decimal("299.00"),
        "price_yearly": Decimal("2990.00"),
        "max_users": 50,
        "max_storage_mb": 5120,
        "is_featured": False,
        "sort_order": 3,
    },
    {
        "slug": "enterprise",
        "name": "企业版",
        "description": "定制化功能与专属支持，适合大型企业和集团",
        "price": Decimal("999.00"),
        "price_yearly": Decimal("9990.00"),
        "max_users": -1,
        "max_storage_mb": 102400,
        "is_featured": False,
        "sort_order": 4,
    },
]

SEED_PERMISSIONS = [
    # ── tenant 模块 ──
    {"slug": "view_tenant", "name": "查看租户", "module": "tenant", "description": "查看租户列表及详情"},
    {"slug": "create_tenant", "name": "创建租户", "module": "tenant", "description": "创建新租户"},
    {"slug": "update_tenant", "name": "更新租户", "module": "tenant", "description": "编辑租户信息"},
    {"slug": "delete_tenant", "name": "删除租户", "module": "tenant", "description": "删除/停用租户"},
    {"slug": "manage_tenant_config", "name": "管理租户配置", "module": "tenant", "description": "管理租户级别的配置项"},

    # ── user 模块 ──
    {"slug": "view_user", "name": "查看用户", "module": "user", "description": "查看用户列表及详情"},
    {"slug": "create_user", "name": "创建用户", "module": "user", "description": "创建新用户"},
    {"slug": "update_user", "name": "更新用户", "module": "user", "description": "编辑用户信息"},
    {"slug": "delete_user", "name": "删除用户", "module": "user", "description": "删除/禁用用户"},
    {"slug": "manage_user_role", "name": "管理用户角色", "module": "user", "description": "为用户分配/更改角色"},

    # ── billing 模块 ──
    {"slug": "view_billing", "name": "查看计费", "module": "billing", "description": "查看计费相关信息和订单"},
    {"slug": "manage_billing", "name": "管理计费", "module": "billing", "description": "管理计费设置和退款"},
    {"slug": "view_invoice", "name": "查看发票", "module": "billing", "description": "查看/下载发票"},
    {"slug": "export_invoice", "name": "导出发票", "module": "billing", "description": "批量导出发票数据"},

    # ── analytics 模块 ──
    {"slug": "view_analytics", "name": "查看分析", "module": "analytics", "description": "查看数据分析面板"},
    {"slug": "export_analytics", "name": "导出分析", "module": "analytics", "description": "导出分析报表"},
    {"slug": "manage_report", "name": "管理报表", "module": "analytics", "description": "创建/编辑自定义报表"},

    # ── system 模块 ──
    {"slug": "view_system_config", "name": "查看系统配置", "module": "system", "description": "查看全局系统配置"},
    {"slug": "manage_system_config", "name": "管理系统配置", "module": "system", "description": "修改全局系统配置"},
    {"slug": "manage_feature_flag", "name": "管理特性开关", "module": "system", "description": "创建/编辑特性开关"},
    {"slug": "view_audit_log", "name": "查看审计日志", "module": "system", "description": "查看操作审计日志"},
]

SEED_GLOBAL_CONFIGS = [
    {
        "key": "system.timezone",
        "name": "系统时区",
        "value": "Asia/Shanghai",
        "config_type": "string",
        "category": "system",
        "default_value": "Asia/Shanghai",
        "is_public": True,
        "description": "系统默认时区",
    },
    {
        "key": "system.language",
        "name": "系统语言",
        "value": "zh-hans",
        "config_type": "string",
        "category": "system",
        "default_value": "zh-hans",
        "is_public": True,
        "description": "系统默认语言",
    },
    {
        "key": "feature.export_enabled",
        "name": "数据导出功能",
        "value": "true",
        "config_type": "boolean",
        "category": "feature",
        "default_value": "true",
        "is_public": False,
        "description": "是否全局启用数据导出功能",
    },
    {
        "key": "system.page_size",
        "name": "默认分页大小",
        "value": "20",
        "config_type": "integer",
        "category": "system",
        "default_value": "20",
        "is_public": True,
        "description": "列表默认每页显示条数",
    },
    {
        "key": "system.session_timeout",
        "name": "会话超时时间",
        "value": "3600",
        "config_type": "integer",
        "category": "system",
        "default_value": "3600",
        "is_public": False,
        "description": "用户会话超时秒数（默认1小时）",
    },
    {
        "key": "security.max_login_attempts",
        "name": "最大登录尝试次数",
        "value": "5",
        "config_type": "integer",
        "category": "security",
        "default_value": "5",
        "is_public": False,
        "description": "账户锁定前允许的最大失败登录次数",
    },
    {
        "key": "business.subscription_grace_days",
        "name": "订阅宽限天数",
        "value": "7",
        "config_type": "integer",
        "category": "business",
        "default_value": "7",
        "is_public": False,
        "description": "订阅过期后仍可使用的宽限天数",
    },
    {
        "key": "system.maintenance_mode",
        "name": "系统维护模式",
        "value": "false",
        "config_type": "boolean",
        "category": "system",
        "default_value": "false",
        "is_public": True,
        "description": "是否进入维护模式（仅管理员可访问）",
    },
]

SEED_FEATURE_FLAGS = [
    {
        "key": "feature.new_dashboard",
        "name": "新版仪表盘",
        "description": "默认禁用，通过灰度发布逐步启用新版仪表盘",
        "status": "draft",
        "rollout_strategy": "all",
        "rollout_percentage": 0,
    },
]

DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "默认租户"
DEFAULT_ROLE_SLUG = "admin"
DEFAULT_ROLE_NAME = "管理员"


class Command(BaseCommand):
    help = "初始化种子数据（套餐、权限、默认租户、角色、全局配置、特性开关），幂等，可重复执行"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="删除已有种子数据后重新创建",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        reset = options["reset"]

        logger.info("种子数据初始化开始 (reset={})", reset)

        if reset:
            self._reset_seed_data()

        self._seed_plans()
        self._seed_permissions()
        self._seed_tenant()
        self._seed_role()
        self._seed_global_configs()
        self._seed_feature_flags()

        logger.success("种子数据初始化完成")
        self.stdout.write(self.style.SUCCESS("\n✅ 种子数据初始化完成"))

    # ------------------------------------------------------------------
    # Reset — 删除已有种子数据
    # ------------------------------------------------------------------
    def _reset_seed_data(self):
        Plan = apps.get_model("saas", "Plan")
        Permission = apps.get_model("saas", "Permission")
        Tenant = apps.get_model("saas", "Tenant")
        Role = apps.get_model("saas", "Role")
        GlobalConfig = apps.get_model("saas", "GlobalConfig")
        FeatureFlag = apps.get_model("saas", "FeatureFlag")

        logger.warning("正在删除已有种子数据 ...")

        # 先删除角色（依赖 Permission 和 Tenant）
        deleted_role, _ = Role.objects.filter(
            slug=DEFAULT_ROLE_SLUG,
            tenant__slug=DEFAULT_TENANT_SLUG,
        ).delete()
        logger.info("  已删除角色: {} 条", deleted_role)

        # 删除默认租户
        deleted_tenant, _ = Tenant.objects.filter(slug=DEFAULT_TENANT_SLUG).delete()
        logger.info("  已删除租户: {} 条", deleted_tenant)

        # 删除权限
        perm_slugs = [p["slug"] for p in SEED_PERMISSIONS]
        deleted_perm, _ = Permission.objects.filter(slug__in=perm_slugs).delete()
        logger.info("  已删除权限: {} 条", deleted_perm)

        # 删除套餐
        plan_slugs = [p["slug"] for p in SEED_PLANS]
        deleted_plan, _ = Plan.objects.filter(slug__in=plan_slugs).delete()
        logger.info("  已删除套餐: {} 条", deleted_plan)

        # 删除全局配置
        config_keys = [c["key"] for c in SEED_GLOBAL_CONFIGS]
        deleted_config, _ = GlobalConfig.objects.filter(key__in=config_keys).delete()
        logger.info("  已删除全局配置: {} 条", deleted_config)

        # 删除特性开关
        flag_keys = [f["key"] for f in SEED_FEATURE_FLAGS]
        deleted_flag, _ = FeatureFlag.objects.filter(key__in=flag_keys).delete()
        logger.info("  已删除特性开关: {} 条", deleted_flag)

    # ------------------------------------------------------------------
    # 1. 套餐
    # ------------------------------------------------------------------
    def _seed_plans(self):
        Plan = apps.get_model("saas", "Plan")  # 延迟导入

        logger.info("── 初始化套餐 ──")
        created = 0
        for item in SEED_PLANS:
            defaults = {
                k: v
                for k, v in item.items()
                if k != "slug"
            }
            # update_or_create 需要所有非唯一字段
            _, is_new = Plan.objects.update_or_create(
                slug=item["slug"],
                defaults=defaults,
            )
            if is_new:
                created += 1
            status = "新建" if is_new else "已存在"
            logger.info("  [{}] {} ({})", status, item["name"], item["slug"])
            self.stdout.write(f"  [{status}] {item['name']} ({item['slug']})")

        logger.success("  套餐初始化完成: 新建 {}, 共 {} 个", created, len(SEED_PLANS))

    # ------------------------------------------------------------------
    # 2. 权限
    # ------------------------------------------------------------------
    def _seed_permissions(self):
        Permission = apps.get_model("saas", "Permission")

        logger.info("── 初始化权限 ──")
        created = 0
        for item in SEED_PERMISSIONS:
            defaults = {
                "name": item["name"],
                "module": item["module"],
                "description": item.get("description", ""),
                "is_active": True,
            }
            _, is_new = Permission.objects.update_or_create(
                slug=item["slug"],
                defaults=defaults,
            )
            if is_new:
                created += 1
            status = "新建" if is_new else "已存在"
            logger.info("  [{}] {}: {}", status, item["slug"], item["name"])
            self.stdout.write(f"  [{status}] {item['slug']} — {item['name']}")

        logger.success("  权限初始化完成: 新建 {}, 共 {} 个", created, len(SEED_PERMISSIONS))

    # ------------------------------------------------------------------
    # 3. 默认租户
    # ------------------------------------------------------------------
    def _seed_tenant(self):
        Plan = apps.get_model("saas", "Plan")
        Tenant = apps.get_model("saas", "Tenant")
        User = apps.get_model("users", "User")

        logger.info("── 初始化默认租户 ──")

        # 尝试绑定免费套餐
        free_plan = Plan.objects.filter(slug="free").first()

        # 尝试绑定第一个超级用户
        admin_user = User.objects.filter(is_superuser=True).first()

        tenant, is_new = Tenant.objects.update_or_create(
            slug=DEFAULT_TENANT_SLUG,
            defaults={
                "name": DEFAULT_TENANT_NAME,
                "domain": "",
                "status": "active",
                "plan": free_plan,
                "created_by": admin_user,
                "description": "系统默认租户，由种子数据自动创建",
            },
        )
        status = "新建" if is_new else "已存在"
        logger.info("  [{}] {} (slug={}, id={})", status, tenant.name, tenant.slug, tenant.id)
        self.stdout.write(f"  [{status}] {tenant.name} ({tenant.slug})")

        return tenant

    # ------------------------------------------------------------------
    # 4. 默认管理员角色
    # ------------------------------------------------------------------
    def _seed_role(self):
        Permission = apps.get_model("saas", "Permission")
        Role = apps.get_model("saas", "Role")
        Tenant = apps.get_model("saas", "Tenant")

        logger.info("── 初始化默认管理员角色 ──")

        default_tenant = Tenant.objects.filter(slug=DEFAULT_TENANT_SLUG).first()
        if default_tenant is None:
            logger.error("  未找到默认租户 (slug={})，跳过角色创建", DEFAULT_TENANT_SLUG)
            self.stderr.write("  ❌ 未找到默认租户，跳过角色创建")
            return

        role, is_new = Role.objects.update_or_create(
            tenant=default_tenant,
            slug=DEFAULT_ROLE_SLUG,
            defaults={
                "name": DEFAULT_ROLE_NAME,
                "description": "系统管理员角色，拥有所有权限",
                "is_system": True,
                "is_active": True,
            },
        )

        # 关联所有权限（兼容已有角色增量补全）
        all_perms = Permission.objects.filter(
            slug__in=[p["slug"] for p in SEED_PERMISSIONS],
            is_active=True,
        )
        existing_slugs = set(role.permissions.values_list("slug", flat=True))
        new_perms = [p for p in all_perms if p.slug not in existing_slugs]
        if new_perms:
            role.permissions.add(*new_perms)
            logger.info("  已为角色添加 {} 个新权限", len(new_perms))

        total_perms = role.permissions.count()
        status = "新建" if is_new else "已存在"
        logger.info("  [{}] {} (slug={}, 权限数={})", status, role.name, role.slug, total_perms)
        self.stdout.write(f"  [{status}] {role.name} ({role.slug}) — {total_perms} 个权限")

        logger.success("  角色初始化完成")

    # ------------------------------------------------------------------
    # 5. 全局配置
    # ------------------------------------------------------------------
    def _seed_global_configs(self):
        GlobalConfig = apps.get_model("saas", "GlobalConfig")

        logger.info("── 初始化全局配置 ──")
        created = 0
        for item in SEED_GLOBAL_CONFIGS:
            defaults = {
                k: v
                for k, v in item.items()
                if k != "key"
            }
            _, is_new = GlobalConfig.objects.update_or_create(
                key=item["key"],
                defaults=defaults,
            )
            if is_new:
                created += 1
            status = "新建" if is_new else "已存在"
            logger.info("  [{}] {} = {}", status, item["key"], item["value"])
            self.stdout.write(f"  [{status}] {item['key']} = {item['value']}")

        logger.success("  全局配置初始化完成: 新建 {}, 共 {} 个", created, len(SEED_GLOBAL_CONFIGS))

    # ------------------------------------------------------------------
    # 6. 特性开关
    # ------------------------------------------------------------------
    def _seed_feature_flags(self):
        FeatureFlag = apps.get_model("saas", "FeatureFlag")

        logger.info("── 初始化特性开关 ──")
        created = 0
        for item in SEED_FEATURE_FLAGS:
            defaults = {
                k: v
                for k, v in item.items()
                if k != "key"
            }
            _, is_new = FeatureFlag.objects.update_or_create(
                key=item["key"],
                defaults=defaults,
            )
            if is_new:
                created += 1
            status = "新建" if is_new else "已存在"
            logger.info("  [{}] {} (status={})", status, item["key"], item["status"])
            self.stdout.write(f"  [{status}] {item['key']} (status={item['status']})")

        logger.success("  特性开关初始化完成: 新建 {}, 共 {} 个", created, len(SEED_FEATURE_FLAGS))
