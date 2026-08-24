#!/usr/bin/env python
"""Django's command-line utility for the notice_service project."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "notice_service.settings")

    # 服务启动横幅 + 启动检查（本地开发命令 runserver/runworker 时触发；
    # 生产 web 入口走 asgi/wsgi，worker 走 celery.py 信号，均已接入）
    if len(sys.argv) > 1 and sys.argv[1] in ("runserver", "runworker"):
        try:
            from framework.log_utils.service_banner import startup_boot
            startup_boot("notice", extra="manage.py " + sys.argv[1])
        except Exception:  # pragma: no cover - 检查失败不阻断开发命令
            pass

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
