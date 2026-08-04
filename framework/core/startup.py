"""
统一启动横幅 / 启动健康检查
============================

在 wsgi.py / asgi.py / celery.py 顶层调用
打印进程 / 环境 / 配置 / 资源初始化结果

核心组件:
  - print_startup_banner: 打印启动横幅
  - StartupChecker: 逐模块启动检查器，记录每个模块的 starting/success/failure
  - log_init_phase: 简单初始化包装器（向后兼容）
"""
from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from loguru import logger


# ---------------------------------------------------------------------------
# 运行时信息
# ---------------------------------------------------------------------------

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
    logger.info(banner)


# ---------------------------------------------------------------------------
# 启动检查器
# ---------------------------------------------------------------------------

class StartupChecker:
    """
    逐模块启动检查器

    每个模块初始化时输出三阶段日志:
      1. INFO  "[startup] {模块名} 正在启动..."
      2. SUCCESS "[startup] {模块名} 启动成功 ({耗时}ms)"
      3. ERROR  "[startup] {模块名} 启动失败 ({耗时}ms): {错误}"

    全部检查完成后调用 summary() 打印汇总表。

    用法::

        checker = StartupChecker()

        # 基础设施初始化（失败不中断）
        checker.run_safe("DB连接池", enable_db_pool)
        checker.run_safe("Sentry", init_sentry)

        # 检查 Django app 可导入性
        checker.check_apps()

        # 关键模块（失败则中断）
        checker.run("审计信号", register_audit_signals)

        # 汇总
        checker.summary()
    """

    def __init__(self) -> None:
        self._results: List[Tuple[str, str, float, Optional[str]]] = []
        # (name, status, cost_ms, error_msg)  status: "ok" | "fail" | "skip"

    # -- 核心方法 --

    def run(self, name: str, fn: Callable, *args, **kwargs):
        """
        执行模块初始化，失败时抛出异常。

        Returns:
            fn 的返回值
        """
        logger.info(f"[startup] {name} 正在启动...")
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            cost = (time.time() - t0) * 1000
            extra = f" -> {result}" if result is not None else ""
            logger.success(f"[startup] {name} 启动成功 ({cost:.1f}ms){extra}")
            self._results.append((name, "ok", cost, None))
            return result
        except Exception as e:
            cost = (time.time() - t0) * 1000
            logger.error(f"[startup] {name} 启动失败 ({cost:.1f}ms): {e}")
            self._results.append((name, "fail", cost, str(e)))
            raise

    def run_safe(self, name: str, fn: Callable, *args, **kwargs):
        """
        同 run()，但失败时只记录日志、不抛异常。
        适用于非关键模块（缺了也能跑）。
        """
        logger.info(f"[startup] {name} 正在启动...")
        t0 = time.time()
        try:
            result = fn(*args, **kwargs)
            cost = (time.time() - t0) * 1000
            extra = f" -> {result}" if result is not None else ""
            logger.success(f"[startup] {name} 启动成功 ({cost:.1f}ms){extra}")
            self._results.append((name, "ok", cost, None))
            return result
        except Exception as e:
            cost = (time.time() - t0) * 1000
            logger.error(f"[startup] {name} 启动失败 ({cost:.1f}ms): {e}")
            self._results.append((name, "fail", cost, str(e)))
            return None

    def skip(self, name: str, reason: str = "") -> None:
        """记录一个被跳过的模块（如未配置、未启用）"""
        msg = f"[startup] {name} 跳过"
        if reason:
            msg += f" ({reason})"
        logger.warning(msg)
        self._results.append((name, "skip", 0.0, reason or None))

    # -- 模块导入检查 --

    def check_import(self, name: str, import_path: str) -> bool:
        """
        检查模块是否可导入（不执行任何操作，仅验证可加载性）。
        """
        logger.info(f"[startup] {name} 正在检查导入...")
        t0 = time.time()
        try:
            __import__(import_path)
            cost = (time.time() - t0) * 1000
            logger.success(f"[startup] {name} 导入检查通过 ({cost:.1f}ms)")
            self._results.append((name, "ok", cost, None))
            return True
        except Exception as e:
            cost = (time.time() - t0) * 1000
            logger.error(f"[startup] {name} 导入检查失败 ({cost:.1f}ms): {e}")
            self._results.append((name, "fail", cost, str(e)))
            return False

    def check_apps(self) -> None:
        """
        遍历 Django INSTALLED_APPS，逐个检查 app 是否可正常加载。
        必须在 Django.setup() 之后调用。
        """
        try:
            from django.apps import apps
        except ImportError:
            self.skip("Django Apps", "Django 未安装")
            return

        logger.info("[startup] Django Apps 正在检查...")
        t0 = time.time()
        ok_count = 0
        fail_count = 0

        for app_config in apps.get_app_configs():
            app_label = app_config.label
            app_name = app_config.name
            try:
                # 尝试导入 app 的 models 模块（最常出问题的部分）
                models_module = app_config.models_module
                verbose = getattr(app_config, "verbose_name", app_label)
                logger.success(f"[startup] App [{app_label}] {verbose} 检查通过")
                ok_count += 1
            except Exception as e:
                logger.error(f"[startup] App [{app_label}] {app_name} 检查失败: {e}")
                fail_count += 1

        cost = (time.time() - t0) * 1000
        status = "ok" if fail_count == 0 else "fail"
        logger.info(
            f"[startup] Django Apps 检查完成: "
            f"{ok_count} ok / {fail_count} fail / {ok_count + fail_count} total "
            f"({cost:.1f}ms)"
        )
        self._results.append(("Django Apps", status, cost, None))

    # -- 汇总 --

    def summary(self) -> dict:
        """
        打印启动汇总表，返回统计字典。
        """
        total = len(self._results)
        ok = sum(1 for _, s, _, _ in self._results if s == "ok")
        fail = sum(1 for _, s, _, _ in self._results if s == "fail")
        skip = sum(1 for _, s, _, _ in self._results if s == "skip")
        total_cost = sum(c for _, _, c, _ in self._results)

        line = "=" * 64

        # 构建表格
        rows = []
        for name, status, cost, err in self._results:
            icon = {"ok": "OK", "fail": "FAIL", "skip": "SKIP"}[status]
            err_str = f" | {err}" if err else ""
            rows.append(f"  {icon:4s} | {name:24s} | {cost:7.1f}ms{err_str}")

        table = "\n".join(rows)
        summary_text = (
            f"\n{line}\n"
            f"  启动检查汇总\n"
            f"{'─' * 64}\n"
            f"{table}\n"
            f"{'─' * 64}\n"
            f"  总计: {ok} 成功 / {fail} 失败 / {skip} 跳过 / {total} 个模块\n"
            f"  总耗时: {total_cost:.1f}ms\n"
            f"{line}"
        )

        if fail > 0:
            logger.warning(summary_text)
        else:
            logger.success(summary_text)

        return {"total": total, "ok": ok, "fail": fail, "skip": skip, "cost_ms": total_cost}

    @property
    def all_ok(self) -> bool:
        """是否全部成功（跳过的不算失败）"""
        return all(s in ("ok", "skip") for _, s, _, _ in self._results)


# ---------------------------------------------------------------------------
# 向后兼容: 旧版 log_init_phase
# ---------------------------------------------------------------------------

def log_init_phase(name: str, fn, *args, **kwargs):
    """
    通用初始化阶段包装器：测量耗时 + 错误捕获
    用法：
        log_init_phase("DB连接池", patch_all_backends)

    .. note::
        新代码建议使用 StartupChecker.run() / run_safe()，
        可获得 starting 日志和汇总表。
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
