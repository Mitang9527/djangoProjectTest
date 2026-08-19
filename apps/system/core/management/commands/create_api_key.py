"""
签发带时效性的 API Key。

用法:
    python manage.py create_api_key "报表导出服务" --user admin --ttl 3600
    python manage.py create_api_key "永久服务账号" --user admin --ttl 0   # 永不过期

说明:
    - 明文密钥仅本次输出可见，库中仅存 SHA256 哈希。
    - ttl 单位为秒；传 0 或省略 --ttl 由 --no-expire 控制永不过期。
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from system.core.models import APIKey


class Command(BaseCommand):
    help = "签发带时效性的 API Key（用于时效性密钥受保护接口）"

    def add_arguments(self, parser):
        parser.add_argument("name", help="密钥用途标识，例如：报表导出服务")
        parser.add_argument("--user", default="admin", help="所属用户名（默认 admin）")
        parser.add_argument(
            "--ttl", type=int, default=3600,
            help="有效秒数（默认 3600）；0 表示永不过期",
        )

    def handle(self, *args, **options):
        name = options["name"]
        ttl = options["ttl"] or None

        User = get_user_model()
        try:
            user = User.objects.get(username=options["user"])
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"用户不存在: {options['user']}"))
            return

        key_obj = APIKey.issue(user, name, ttl_seconds=ttl)
        self.stdout.write(self.style.SUCCESS(f"已签发密钥（明文仅显示一次）: {key_obj.key}"))
        self.stdout.write(
            f"  name        = {key_obj.name}\n"
            f"  owner       = {user.username}\n"
            f"  expires_at  = {key_obj.expires_at}  ({'永不过期' if key_obj.expires_at is None else '带时效性'})"
        )
        self.stdout.write(
            self.style.WARNING("请妥善保存上方明文密钥；库内仅存哈希，无法再次查询。")
        )
