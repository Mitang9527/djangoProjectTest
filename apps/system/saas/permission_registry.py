"""
内置权限注册表
==============
定义系统内所有权限点，供 init_permissions 管理命令入库。
每个权限点对应 Permission 模型的一行记录。

字段说明：
  slug    → Permission.slug（唯一标识，与 PermissionSlug 常量对应）
  name    → 友好中文名称
  module  → 字符串，对应 Permission.Module 枚举值（tenant/user/billing/analytics/system）
  desc    → 简短描述
"""

# ---------------------------------------------------------------------------
# 权限点定义列表
# ---------------------------------------------------------------------------
BUILTIN_PERMISSIONS = [
    # ── 系统管理 ──────────────────────────────────────────────
    {
        "slug": "system.view",
        "name": "查看系统管理",
        "module": "system",
        "desc": "可以查看系统管理相关页面和数据",
    },
    {
        "slug": "system.manage",
        "name": "管理系统",
        "module": "system",
        "desc": "可以管理系统后台等平台级资源（菜单/文件资产等）",
    },
    {
        "slug": "system.dashboard",
        "name": "查看系统仪表板",
        "module": "system",
        "desc": "可以查看系统概览和统计数据",
    },
    {
        "slug": "system.logs.view",
        "name": "查看系统日志",
        "module": "system",
        "desc": "可以查看系统操作日志和错误日志",
    },
    {
        "slug": "system.logs.manage",
        "name": "管理系统日志",
        "module": "system",
        "desc": "可以导出和清理系统日志",
    },

    # ── 系统设置 ──────────────────────────────────────────────
    {
        "slug": "system.settings.view",
        "name": "查看系统设置",
        "module": "system",
        "desc": "可以查看系统基础配置信息",
    },
    {
        "slug": "system.settings.basic",
        "name": "基本设置管理",
        "module": "system",
        "desc": "可以修改系统名称、描述等基本信息",
    },
    {
        "slug": "system.settings.security",
        "name": "安全设置管理",
        "module": "system",
        "desc": "可以配置密码策略、登录限制等安全选项",
    },
    {
        "slug": "system.settings.notification",
        "name": "通知设置管理",
        "module": "system",
        "desc": "可以配置邮件、短信等通知服务",
    },
    {
        "slug": "system.settings.integration",
        "name": "集成设置管理",
        "module": "system",
        "desc": "可以配置第三方服务集成",
    },
    {
        "slug": "system.settings.backup",
        "name": "备份恢复管理",
        "module": "system",
        "desc": "可以执行数据备份和恢复操作",
    },

    # ── 租户管理 ──────────────────────────────────────────────
    {
        "slug": "tenant.view",
        "name": "查看租户",
        "module": "tenant",
        "desc": "可以查看租户列表和详情",
    },
    {
        "slug": "tenant.manage",
        "name": "管理租户",
        "module": "tenant",
        "desc": "可以创建、编辑、停用租户",
    },

    # ── 用户/成员管理 ─────────────────────────────────────────
    {
        "slug": "user.view",
        "name": "查看用户",
        "module": "user",
        "desc": "可以查看成员列表和用户信息",
    },
    {
        "slug": "user.manage",
        "name": "管理用户",
        "module": "user",
        "desc": "可以邀请成员、修改角色、停用账号",
    },

    # ── 角色 & 权限管理 ───────────────────────────────────────
    {
        "slug": "role.view",
        "name": "查看角色",
        "module": "system",
        "desc": "可以查看角色列表和权限配置",
    },
    {
        "slug": "role.manage",
        "name": "管理角色",
        "module": "system",
        "desc": "可以创建/编辑角色并分配权限",
    },

    # ── 套餐管理 ──────────────────────────────────────────────
    {
        "slug": "billing.plan.view",
        "name": "查看套餐",
        "module": "billing",
        "desc": "可以查看套餐和功能列表",
    },
    {
        "slug": "billing.plan.manage",
        "name": "管理套餐",
        "module": "billing",
        "desc": "可以创建、修改、下架套餐",
    },

    # ── 订阅管理 ──────────────────────────────────────────────
    {
        "slug": "billing.subscription.view",
        "name": "查看订阅",
        "module": "billing",
        "desc": "可以查看租户订阅状态和到期时间",
    },
    {
        "slug": "billing.subscription.manage",
        "name": "管理订阅",
        "module": "billing",
        "desc": "可以变更订阅套餐、手动续期",
    },

    # ── 订单管理 ──────────────────────────────────────────────
    {
        "slug": "billing.order.view",
        "name": "查看订单",
        "module": "billing",
        "desc": "可以查看订单列表和支付状态",
    },
    {
        "slug": "billing.order.manage",
        "name": "管理订单",
        "module": "billing",
        "desc": "可以处理退款、手动核销订单",
    },

    # ── 发票管理 ──────────────────────────────────────────────
    {
        "slug": "billing.invoice.view",
        "name": "查看发票",
        "module": "billing",
        "desc": "可以查看发票列表和下载 PDF",
    },
    {
        "slug": "billing.invoice.manage",
        "name": "管理发票",
        "module": "billing",
        "desc": "可以开具、作废发票",
    },

    # ── ADB 设备管理 ──────────────────────────────────────────
    {
        "slug": "adb.view",
        "name": "查看 ADB 设备",
        "module": "system",
        "desc": "可以查看已连接设备列表和基本信息",
    },
    {
        "slug": "adb.operate",
        "name": "操作 ADB 设备",
        "module": "system",
        "desc": "可以执行截图、Shell 命令、安装应用等操作",
    },

    # ── API 网关管理 ──────────────────────────────────────────
    {
        "slug": "gateway.view",
        "name": "查看网关配置",
        "module": "system",
        "desc": "可以查看 API 网关仪表盘和限流规则列表",
    },
    {
        "slug": "gateway.manage",
        "name": "管理网关配置",
        "module": "system",
        "desc": "可以创建、编辑、删除 API 限流规则",
    },

    # ── 系统配置（保留原有配置用于兼容性）──────────────────────
    {
        "slug": "config.view",
        "name": "查看系统配置",
        "module": "system",
        "desc": "可以查看系统设置页面（兼容旧版）",
    },
    {
        "slug": "config.manage",
        "name": "管理系统配置",
        "module": "system",
        "desc": "可以修改语言、主题等系统设置（兼容旧版）",
    },

    # ── 字典管理（对齐 Fast-Vben-Admin system:dict:*）─────────
    {
        "slug": "dict.view",
        "name": "查看字典",
        "module": "system",
        "desc": "可以查看字典类型与字典项",
    },
    {
        "slug": "dict.manage",
        "name": "管理字典",
        "module": "system",
        "desc": "可以创建、编辑、删除字典类型与字典项",
    },

    # ── 文件资产（对齐 Fast-Vben-Admin file asset 管理）───────
    {
        "slug": "file.view",
        "name": "查看文件资产",
        "module": "system",
        "desc": "可以查看文件资产列表与详情",
    },
    {
        "slug": "file.manage",
        "name": "管理文件资产",
        "module": "system",
        "desc": "可以删除、恢复文件资产",
    },
]


# ---------------------------------------------------------------------------
# 所有权限 slug 集合 —— 用于"超级管理员角色"自动关联全部权限
# ---------------------------------------------------------------------------
ALL_PERMISSION_SLUGS = [p["slug"] for p in BUILTIN_PERMISSIONS]


# ---------------------------------------------------------------------------
# 预置角色定义
# ---------------------------------------------------------------------------
BUILTIN_ROLES = [
    {
        "name": "超级管理员",
        "slug": "super-admin",
        "desc": "拥有系统全部权限，由系统自动创建",
        "is_system": True,
        "permissions": ALL_PERMISSION_SLUGS,   # 关联全部
    },
    {
        "name": "系统管理员",
        "slug": "system-admin",
        "desc": "负责系统管理和设置，但不涉及租户和用户管理",
        "is_system": True,
        "permissions": [
            "system.view",
            "system.dashboard",
            "system.logs.view",
            "system.logs.manage",
            "system.settings.view",
            "system.settings.basic",
            "system.settings.security",
            "system.settings.notification",
            "system.settings.integration",
            "system.settings.backup",
            "role.view",
            "role.manage",
            "adb.view",
            "adb.operate",
            "config.view",
            "config.manage",
            "gateway.view",
            "gateway.manage",
        ],
    },
    {
        "name": "普通成员",
        "slug": "member",
        "desc": "只读权限，仅可查看，不可修改",
        "is_system": True,
        "permissions": [
            "system.view",
            "system.dashboard",
            "system.settings.view",
            "tenant.view",
            "user.view",
            "role.view",
            "billing.plan.view",
            "billing.order.view",
            "adb.view",
            "config.view",
        ],
    },
    {
        "name": "财务人员",
        "slug": "finance",
        "desc": "负责订单、发票和订阅管理",
        "is_system": True,
        "permissions": [
            "system.view",
            "system.dashboard",
            "billing.plan.view",
            "billing.subscription.view",
            "billing.subscription.manage",
            "billing.order.view",
            "billing.order.manage",
            "billing.invoice.view",
            "billing.invoice.manage",
            "config.view",
        ],
    },
    {
        "name": "设备运维",
        "slug": "adb-operator",
        "desc": "专注 ADB 设备管理，无业务数据访问权",
        "is_system": True,
        "permissions": [
            "system.view",
            "adb.view",
            "adb.operate",
        ],
    },
]
