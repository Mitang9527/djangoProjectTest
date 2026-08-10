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
    else:
        raise ValueError(f"未知的运行环境: {get_env_type()}")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
    
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
