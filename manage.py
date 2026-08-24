#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from framework.core.env_loader import load_env_file, get_env_type, is_production, is_development


def main():
    """Run administrative tasks."""
    # 加载环境变量
    load_env_file()
    
    # 获取环境类型，决定加载哪个 settings
    if is_production():
        default_settings = "djangoProjectTest.settings.prod"
    elif is_development():
        default_settings = "djangoProjectTest.settings.dev"
    elif get_env_type() == "TEST":
        # CI / 本地测试环境（pytest 走 pyproject 的 DJANGO_SETTINGS_MODULE，
        # 这里覆盖 manage.py 命令如 makemigrations --check 的场景）
        default_settings = "djangoProjectTest.settings.test"
    else:
        raise ValueError(f"未知的运行环境: {get_env_type()}")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

    # 服务启动横幅 + 启动检查（本地开发命令 runserver/runworker 时触发；
    # 生产 web 入口走 asgi/wsgi，worker 走 celery.py 信号，均已接入）
    if len(sys.argv) > 1 and sys.argv[1] in ("runserver", "runworker"):
        try:
            from framework.log_utils.service_banner import startup_boot
            startup_boot("main", extra="manage.py " + sys.argv[1])
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
