"""
初始化 API 网关默认限流规则
"""
from django.core.management.base import BaseCommand
from system.saas.models import APILimitRule


DEFAULT_RULES = [
    {
        "name": "数据导出接口限流",
        "url_pattern": "/saas/api/export/",
        "throttle_type": "ip",
        "rate": "10/m",
        "priority": 0,
        "description": "限制数据导出接口频率，防止大量导出拖垮服务器",
    },
    {
        "name": "API 全局 IP 限流",
        "url_pattern": "/api/*",
        "throttle_type": "ip",
        "rate": "500/h",
        "priority": 100,
        "description": "全局 API IP 限流兜底规则（优先级最低）",
    },
    {
        "name": "SaaS API 全局 IP 限流",
        "url_pattern": "/saas/api/*",
        "throttle_type": "ip",
        "rate": "500/h",
        "priority": 100,
        "description": "SaaS 管理后台 API 全局 IP 限流",
    },
]


class Command(BaseCommand):
    help = "初始化 API 网关默认限流规则"

    def handle(self, *args, **options):
        created = 0
        skipped = 0

        for rule_data in DEFAULT_RULES:
            exists = APILimitRule.objects.filter(
                name=rule_data["name"],
                url_pattern=rule_data["url_pattern"],
            ).exists()

            if exists:
                skipped += 1
                self.stdout.write(f"  [已存在] {rule_data['name']}")
            else:
                APILimitRule.objects.create(**rule_data)
                created += 1
                self.stdout.write(f"  [新建] {rule_data['name']}")

        self.stdout.write(f"\n  限流规则：新建 {created} 条，跳过 {skipped} 条，共 {len(DEFAULT_RULES)} 条")
        self.stdout.write(self.style.SUCCESS("API 网关默认规则初始化完成"))
