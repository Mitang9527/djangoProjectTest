# -*- coding: utf-8 -*-
"""
服务启动横幅 (service startup banner)

用于在控制台中明确标识"当前启动的是哪一个服务"，方便在 PyCharm / 终端里
同时运行多个 Django 服务时快速区分。

设计原则:
  - 零第三方依赖 (仅用标准库)，子服务即便 import 不到 framework 也不会崩。
  - 纯 ANSI 转义上色，PyCharm 运行控制台 / 主流终端均可渲染。
  - 同一进程只打印一次 (用环境变量去重)，即便 wsgi/asgi 都被导入也安全。
  - 仅在 wsgi.py / asgi.py 顶层调用，因此只在 web 服务启动 (runserver /
    Daphne / uvicorn) 时触发，migrate / shell / celery 等命令不受影响。
"""

import datetime
import os

# 服务注册表: key -> (短标签, 显示名, 描述, ANSI 颜色码)
#  短标签用于「无 ANSI 颜色渲染」时也能一眼区分 (如 PyCharm 默认控制台)
_SERVICES = {
    "main": (
        "MAIN",
        "Django Main Platform",
        "Web API · multi-tenant SaaS monolith",
        "32",   # green
    ),
    "ai_studio": (
        "AI",
        "AI Studio Service",
        "AI content generation · WebSocket + Celery",
        "36",   # cyan
    ),
    "notice": (
        "NOTICE",
        "Notice Service",
        "Notification dispatch · email/dingtalk/feishu/wechat",
        "35",   # magenta
    ),
    # ---- Celery Worker (亮色系, 与对应 web 服务区分) ----
    "celery_main": (
        "CELERY·MAIN",
        "Celery Worker · Main Platform",
        "async tasks · queue=celery",
        "93",   # bright yellow
    ),
    "celery_ai": (
        "CELERY·AI",
        "Celery Worker · AI Studio",
        "async generation · queue=ai_studio.generate",
        "94",   # bright blue
    ),
    "celery_notice": (
        "CELERY·NOTICE",
        "Celery Worker · Notice Service",
        "notification dispatch · queue=notice.send",
        "95",   # bright magenta
    ),
}

# 防止同一进程重复打印 (wsgi 与 asgi 可能都被导入)
_SHOWN_ENV_KEY = "_SERVICE_BANNER_SHOWN"


def emit_startup_banner(service_key: str, extra: str = None) -> None:
    """
    打印服务启动横幅。

    Args:
        service_key: 服务标识, 取 _SERVICES 的 key ("main" / "ai_studio" / "notice")。
        extra:       可选附加行 (如实际监听端口), 留空则不显示。
    """
    if os.environ.get(_SHOWN_ENV_KEY):
        return
    os.environ[_SHOWN_ENV_KEY] = "1"

    tag, display, desc, color = _SERVICES.get(
        service_key, (service_key.upper(), service_key, "", "37")
    )

    pid = os.getpid()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    worker = os.environ.get("WORKER_TYPE", "-")

    # 第 1 行放短标签 [MAIN]/[AI]/[NOTICE]——即便终端不渲染颜色也一眼可辨
    # settings 行: 暴露实际加载的 DJANGO_SETTINGS_MODULE, 便于发现「启动配置指错模块」
    #   (例如三个配置都跑成 main —— 即都加载了 djangoProjectTest.settings.*)
    settings_mod = os.environ.get("DJANGO_SETTINGS_MODULE", "-")
    lines = [
        f"[{tag}]",
        display,
        desc,
        f"pid={pid}  started={now}  worker={worker}",
        f"settings={settings_mod}",
    ]
    if extra:
        lines.append(extra)

    inner = max(len(l) for l in lines)
    top = "╔" + "═" * (inner + 2) + "╗"
    bottom = "╚" + "═" * (inner + 2) + "╝"
    body = "\n".join("║ " + l.ljust(inner) + " ║" for l in lines)

    banner = (
        f"\n\033[1;{color}m{top}\n{body}\n{bottom}\033[0m\n"
    )
    # 打印到 stdout, flush 保证立即可见 (PyCharm 控制台会渲染 ANSI 颜色)
    print(banner, flush=True)
