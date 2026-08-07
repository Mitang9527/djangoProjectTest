#!/usr/bin/env python
"""AI 创作工作室 — 独立服务管理入口

本文件是独立 Django 工程（不依赖主平台 monolith）的入口。
身份采用解耦 JWT 方案：仅校验主平台签发的 JWT（共享密钥），不在本服务内维护用户表。
"""
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_studio_service.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
