"""
统一启动横幅 / 启动健康检查
============================

在 wsgi.py / asgi.py / celery.py 顶层调用
打印进程 / 环境 / 配置 / 资源初始化结果
"""
from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime
from typing import Optional

from loguru import logger


def _collect_runtime_info(worker: str) -> dict:
    pid = os.getpid()
    ppid = os.getppid()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    env = os.environ.get("ENV", "DEV").upper()
    settings_mod = os.environ.get("DJANGO_SETTINGS_MODULE", "?")
    debug = os.environ.get("DJANGO_DEBUG") or os.environ.get("DEBUG", "?")
    redis_on = "redis" in os.environ.get("REDIS_ENABLED", "").lower() or os.environ.get("REDIS_HOST", "") != ""

    return {
        "worker": worker,
        "pid": pid,
        "ppid": ppid,
        "env": env,
        "settings": settings_mod,
        "debug": debug,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "os": f"{platform.system()} {platform.release()}",
        "redis": "on" if redis_on else "off",
        "started": now,
    }


def _format_banner(info: dict) -> str:
    line = "=" * 64
    return (
        f"\n{line}\n"
        f"  DjangoProjectTest  启动\n"
        f"  worker   : {info['worker']}\n"
        f"  pid      : {info['pid']} (parent: {info['ppid']})\n"
        f"  env      : {info['env']}\n"
        f"  settings : {info['settings']}\n"
        f"  debug    : {info['debug']}\n"
        f"  python   : {info['python']}  ({info['os']})\n"
        f"  redis    : {info['redis']}\n"
        f"  started  : {info['started']}\n"
        f"{line}"
    )


def print_startup_banner(worker: str = "wsgi", extra: Optional[dict] = None) -> None:
    """
    打印启动横幅
    Args:
        worker: wsgi / asgi / celery / manage
        extra:  附加信息字典，会以 - key=value 形式附加在横幅后
    """
    info = _collect_runtime_info(worker)
    banner = _format_banner(info)
    if extra:
        extras = "\n".join(f"  {k:9s}: {v}" for k, v in extra.items())
        banner = banner + "\n" + extras + "\n" + "=" * 64
    # loguru 接管 stdout 后 logger.info 与 print 会重复，这里只走 logger
    logger.info(banner)


def log_init_phase(name: str, fn, *args, **kwargs):
    """
    通用初始化阶段包装器：测量耗时 + 错误捕获
    用法：
        log_init_phase("DB连接池", patch_all_backends)
    """
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        cost = (time.time() - t0) * 1000
        logger.success(f"[init] {name} ok ({cost:.1f}ms){' -> ' + str(result) if result is not None else ''}")
        return result
    except Exception as e:
        cost = (time.time() - t0) * 1000
        logger.error(f"[init] {name} failed ({cost:.1f}ms): {e}")
        raise
