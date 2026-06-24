"""
管理命令：初始化内置权限和预置角色
用法：
    python manage.py init_permissions
    python manage.py init_permissions --reset   # 重建（危险：清空非系统角色之外的权限关联）
"""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.saas.permission_registry import BUILTIN_PERMISSIONS, BUILTIN_ROLES


class Command(BaseCommand):
    help = "初始化 SaaS 内置权限点和预置角色（幂等，可重复执行）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="重置：更新已存在的权限/角色（不删除数据，仅补全缺失项）",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("── 初始化权限点 ──"))
        perm_map = self._sync_permissions()

        self.stdout.write(self.style.MIGRATE_HEADING("\n── 初始化预置角色 ──"))
        self._sync_roles(perm_map)

        self.stdout.write(self.style.SUCCESS("\n✅ 权限初始化完成"))

    # ------------------------------------------------------------------
    # 同步权限点
    # ------------------------------------------------------------------
    def _sync_permissions(self) -> dict[str, object]:
        Permission = apps.get_model("saas", "Permission")  # 延迟导入
        perm_map: dict[str, object] = {}
        created_count = 0
        updated_count = 0

        for item in BUILTIN_PERMISSIONS:
            obj, created = Permission.objects.get_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "module": item["module"],
                    "description": item.get("desc", ""),
                    "is_active": True,
                },
            )
            if not created:
                # 已存在则更新名称/描述（保留 is_active 状态）
                changed = False
                if obj.name != item["name"]:
                    obj.name = item["name"]
                    changed = True
                if obj.description != item.get("desc", ""):
                    obj.description = item.get("desc", "")
                    changed = True
                if changed:
                    obj.save(update_fields=["name", "description"])
                    updated_count += 1
            else:
                created_count += 1

            perm_map[item["slug"]] = obj

            status = "新建" if created else "已存在"
            self.stdout.write(f"  [{status}] {obj.slug} — {obj.name}")

        self.stdout.write(
            f"\n  权限点：新建 {created_count} 个，更新 {updated_count} 个，"
            f"共 {len(BUILTIN_PERMISSIONS)} 个"
        )
        return perm_map

    # ------------------------------------------------------------------
    # 同步角色
    # ------------------------------------------------------------------
    def _sync_roles(self, perm_map: dict[str, object]) -> None:
        Role = apps.get_model("saas", "Role")  # 延迟导入
        created_count = 0

        for item in BUILTIN_ROLES:
            role, created = Role.objects.get_or_create(
                slug=item["slug"],
                tenant=None,         # 系统级角色不绑定租户
                defaults={
                    "name": item["name"],
                    "description": item.get("desc", ""),
                    "is_system": item.get("is_system", False),
                    "is_active": True,
                },
            )
            if not created:
                # 更新名称/描述
                role.name = item["name"]
                role.description = item.get("desc", "")
                role.is_system = item.get("is_system", False)
                role.save(update_fields=["name", "description", "is_system"])

            # 重新关联权限（补全缺失，不删除已有）
            perm_slugs: list[str] = item.get("permissions", [])
            perms_to_add = [perm_map[s] for s in perm_slugs if s in perm_map]
            existing_slugs = set(role.permissions.values_list("slug", flat=True))
            new_perms = [p for p in perms_to_add if p.slug not in existing_slugs]
            if new_perms:
                role.permissions.add(*new_perms)

            if created:
                created_count += 1

            status = "新建" if created else "已存在"
            self.stdout.write(
                f"  [{status}] {role.slug} — {role.name}"
                f"（{role.permissions.count()} 个权限）"
            )

        self.stdout.write(f"\n  角色：新建 {created_count} 个，共 {len(BUILTIN_ROLES)} 个")
