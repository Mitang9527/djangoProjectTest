"""
权限-菜单一致性校验：Menu.permission 非空值必须存在于 Permission 表。

背景：菜单/按钮节点通过 ``permission`` 字段绑定 ``Permission.slug``，种子或手工
维护可能产生脏引用（权限被删 / 拼写错误），导致 my-menus 过滤时该节点对所有人
不可见（权限码永远不匹配）。本命令扫描全部菜单并报告：

- 硬错误（exit 1）：permission 在 Permission 表完全不存在；
- 软警告：permission 存在但 is_active=False（权限停用 → 菜单同样不可见）。

用法::

    python manage.py check_menu_permissions
    python manage.py check_menu_permissions --exit-code   # CI 可集成，有硬错误返回非零
"""

from django.core.management.base import BaseCommand

from system.core.models import Menu
from system.saas.models import Permission


class Command(BaseCommand):
    help = "校验菜单权限码一致性：Menu.permission 非空值必须存在于 Permission 表"

    def add_arguments(self, parser):
        parser.add_argument(
            '--exit-code', action='store_true',
            help='存在硬错误（权限码不存在）时以非零退出码结束，供 CI 集成',
        )

    def handle(self, *args, **options):
        # 权限表全量 slug（含停用，用于区分"不存在"与"已停用"）
        perm_map = {
            slug: active
            for slug, active in Permission.objects.values_list('slug', 'is_active')
        }

        missing = []   # (菜单名, 类型, 权限码) —— 硬错误
        inactive = []  # (菜单名, 类型, 权限码) —— 软警告
        button_no_perm = []  # (菜单名,) —— 按钮缺权限码

        for menu in Menu.objects.all().order_by('sort', 'created_at'):
            if menu.type == Menu.Type.BUTTON and not menu.permission:
                button_no_perm.append(menu.name)
                continue
            if not menu.permission:
                continue
            if menu.permission not in perm_map:
                missing.append((menu.name, menu.type, menu.permission))
            elif not perm_map[menu.permission]:
                inactive.append((menu.name, menu.type, menu.permission))

        total = Menu.objects.count()
        self.stdout.write(f"共检查 {total} 个菜单节点")

        if button_no_perm:
            self.stdout.write(self.style.WARNING(
                f"[警告] {len(button_no_perm)} 个按钮未绑定权限码（前端 v-permission 将失效）: "
                + ", ".join(button_no_perm)
            ))

        if inactive:
            self.stdout.write(self.style.WARNING(
                f"[软警告] {len(inactive)} 个节点绑定的权限已停用（对应菜单对所有人不可见）:"
            ))
            for name, mtype, slug in inactive:
                self.stdout.write(f"  - {name} ({mtype}) -> {slug} [inactive]")

        if missing:
            self.stdout.write(self.style.ERROR(
                f"[硬错误] {len(missing)} 个节点绑定了 Permission 表不存在的权限码:"
            ))
            for name, mtype, slug in missing:
                self.stdout.write(f"  - {name} ({mtype}) -> {slug}")

        if not (missing or inactive or button_no_perm):
            self.stdout.write(self.style.SUCCESS("✓ 全部菜单权限码一致"))
            return

        if missing and options['exit_code']:
            raise SystemExit(1)
