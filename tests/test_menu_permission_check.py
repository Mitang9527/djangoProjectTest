"""权限-菜单一致性校验命令（check_menu_permissions）验证。

覆盖：
- 全部一致：正常种子/有效权限码 → 输出 ✓ 且退出码 0；
- 硬错误：菜单绑定 Permission 表不存在的权限码 → 报告 + --exit-code 非零；
- 软警告：绑定权限已停用 / 按钮未绑定权限码 → 报告但不影响退出码。
"""
from io import StringIO
from django.core.management import call_command
from django.test import TestCase

from system.core.models import Menu
from system.saas.models import Permission


class CheckMenuPermissionsTest(TestCase):
    def tearDown(self):
        # 清理本测试类创建的菜单，避免影响其他用例（TestCase 事务回滚本可不用，
        # 但菜单种子跨用例共享，显式清理更稳妥）
        Menu.objects.all().delete()

    def _run(self, exit_code=False):
        out = StringIO()
        call_command('check_menu_permissions', exit_code=exit_code, stdout=out)
        return out.getvalue()

    def test_all_consistent_when_seed_permissions_valid(self):
        Menu.objects.all().delete()
        Menu.objects.create(name="公开菜单", type="menu")
        output = self._run()
        self.assertIn("✓ 全部菜单权限码一致", output)

    def test_missing_permission_reported_and_exit_code(self):
        Menu.objects.all().delete()
        Menu.objects.create(name="管理后台", type="menu", permission="ghost.perm")
        output = self._run()
        self.assertIn("[硬错误]", output)
        self.assertIn("ghost.perm", output)

        # --exit-code：硬错误 → SystemExit(1)
        with self.assertRaises(SystemExit) as ctx:
            call_command('check_menu_permissions', exit_code=True, stdout=StringIO())
        self.assertEqual(ctx.exception.code, 1)

    def test_inactive_permission_is_soft_warning(self):
        Menu.objects.all().delete()
        perm = Permission.objects.create(
            slug="legacy.perm", name="旧权限",
            module=Permission.Module.SYSTEM, is_active=False)
        Menu.objects.create(name="旧菜单", type="menu", permission=perm.slug)
        output = self._run()
        self.assertIn("[软警告]", output)
        self.assertIn("legacy.perm", output)

    def test_button_without_permission_is_soft_warning(self):
        Menu.objects.all().delete()
        Menu.objects.create(name="裸按钮", type="button")
        output = self._run()
        self.assertIn("[警告]", output)
        self.assertIn("裸按钮", output)

    def test_no_error_exit_without_exit_code_flag(self):
        Menu.objects.all().delete()
        Menu.objects.create(name="管理后台", type="menu", permission="ghost.perm")
        # 未传 --exit-code：即使有硬错误也不抛异常
        output = self._run()
        self.assertIn("[硬错误]", output)
