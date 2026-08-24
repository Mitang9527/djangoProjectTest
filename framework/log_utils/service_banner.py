"""
服务启动横幅 + 启动检查（所有 Django 服务统一入口）。

历史背景：各服务 (asgi/wsgi/celery/manage) 里都 try/except import
`framework.log_utils.service_banner.emit_startup_banner` 并降级为纯 print，
但本模块此前从未实现 —— 所有启动横幅实际都是降级版。本文件补上真实实现，
并新增启动检查能力：

    emit_startup_banner(key, extra=None)   # 启动横幅（settings 加载前即可用）
    run_startup_checks(service, ...)       # 依赖/配置启动检查（需 Django settings）
    startup_boot(service, ...)             # 横幅 + 检查 一步到位（推荐入口）

启动检查项（按服务自动适配）:
    - database     DB 连通性（sqlite 直连 / postgres&mysql 先 socket 探测再 SELECT 1）
    - redis        缓存 Redis ping（仅 django_redis 后端；locmem 跳过）
    - broker       Celery broker 连通性（kombu 连接 ping，支持 redis:// 与 amqp://）
    - env          必需环境变量 / 渠道凭证检查

控制开关（环境变量）:
    STARTUP_CHECKS_ENABLED=0   完全跳过启动检查（默认 1）
    STARTUP_CHECKS_FATAL=1     任一项失败即退出进程（默认 0：仅 WARN 不阻断）
    STARTUP_CHECKS_TIMEOUT     单检查超时秒数（默认 5，仅影响协议级验证）

用法（各服务 asgi.py / wsgi.py 顶部）:
    from framework.log_utils.service_banner import startup_boot
    startup_boot("main")

Celery worker（celery.py worker_init/worker_process_init 信号里）:
    startup_boot("celery_main", extra=f"host={...}")
"""

import os
import socket
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------
# 服务元信息（banner 展示用）
# ---------------------------------------------------------------

_SERVICE_NAMES = {
    "main": "Django 企业级主平台",
    "celery_main": "主平台 Celery Worker",
    "notice": "通知服务 notice_service",
    "celery_notice": "通知服务 Celery Worker",
    "ai_studio": "AI 创作工作室 ai_studio",
    "celery_ai": "AI Studio Celery Worker",
}

_CHECK_TIMEOUT = float(os.environ.get("STARTUP_CHECKS_TIMEOUT", "5"))


# ---------------------------------------------------------------
# 检查结果模型
# ---------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False
    duration_ms: float = 0.0

    def line(self) -> str:
        if self.skipped:
            mark = "SKIP"
        elif self.ok:
            mark = "OK  "
        else:
            mark = "FAIL"
        return (
            f"[{mark}] {self.name:<16} {self.detail} "
            f"({self.duration_ms:.0f}ms)"
        )


CheckFn = Callable[[], CheckResult]


# ---------------------------------------------------------------
# 底层工具
# ---------------------------------------------------------------

def _log(msg: str, level: str = "info") -> None:
    """优先走 loguru（settings 加载后可用），否则 print 兜底。"""
    try:
        from loguru import logger
        getattr(logger, level)(msg)
    except Exception:
        print(f"[{level.upper()}] {msg}", flush=True)


def _probe_port(host: str, port: int, timeout: float = 3.0) -> None:
    """TCP 快速探测端口（失败抛异常）。localhost 归一化为 127.0.0.1。"""
    if not host or host in ("localhost", "::1", "0.0.0.0"):
        host = "127.0.0.1"
    sock = socket.create_connection((host, int(port)), timeout=timeout)
    sock.close()


def _ensure_django() -> Optional[str]:
    """幂等 django.setup()；失败返回错误信息，成功返回 None。"""
    try:
        import django
        from django.conf import settings as dj_settings
        if not dj_settings.configured:
            if not os.environ.get("DJANGO_SETTINGS_MODULE"):
                return "DJANGO_SETTINGS_MODULE 未设置（无法加载 settings）"
            django.setup()
        return None
    except Exception as exc:  # pragma: no cover - 防御性
        return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------
# 内置检查器
# ---------------------------------------------------------------

def check_database(label: str = "database") -> CheckResult:
    """DB 连通性：sqlite 直连；postgres/mysql 先 socket 探测再 SELECT 1。"""
    start = time.monotonic()
    err = _ensure_django()
    if err:
        return CheckResult(label, False, f"django 未就绪: {err}", duration_ms=_ms(start))
    from django.db import connection

    sd = connection.settings_dict
    engine = (sd.get("ENGINE") or "").lower()
    try:
        if "sqlite" in engine:
            connection.ensure_connection()
        else:
            host = sd.get("HOST") or "127.0.0.1"
            port = sd.get("PORT") or (5432 if "postgres" in engine else 3306)
            _probe_port(host, port, timeout=min(_CHECK_TIMEOUT, 3.0))
            connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return CheckResult(label, True, f"engine={engine or '?'}", duration_ms=_ms(start))
    except Exception as exc:
        return CheckResult(label, False, f"{type(exc).__name__}: {exc}", duration_ms=_ms(start))


def check_broker(label: str = "broker") -> CheckResult:
    """Celery broker 连通性（kombu，支持 redis:// 与 amqp://）。未配置则跳过。"""
    start = time.monotonic()
    err = _ensure_django()
    if err:
        return CheckResult(label, False, f"django 未就绪: {err}", duration_ms=_ms(start))
    from django.conf import settings

    url = getattr(settings, "CELERY_BROKER_URL", None)
    if not url:
        return CheckResult(label, True, "未配置 CELERY_BROKER_URL，跳过", skipped=True, duration_ms=_ms(start))
    try:
        # 先 socket 预探测：DNS 解析失败/端口拒绝立即返回，避免 kombu 内部重试拖慢启动
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (5672 if parsed.scheme == "amqp" else 6379)
        _probe_port(host, port, timeout=min(_CHECK_TIMEOUT, 3.0))

        from kombu import Connection

        conn = Connection(url, connect_timeout=_CHECK_TIMEOUT,
                          transport_options={"max_retries": 0})
        try:
            conn.connect()
        finally:
            conn.release()
        return CheckResult(label, True, url.split("@")[-1], duration_ms=_ms(start))
    except Exception as exc:
        return CheckResult(label, False, f"{type(exc).__name__}: {exc}", duration_ms=_ms(start))


def check_redis_from_cache(label: str = "redis") -> CheckResult:
    """读 settings.CACHES['default']，django_redis 后端时 ping；否则跳过。"""
    start = time.monotonic()
    err = _ensure_django()
    if err:
        return CheckResult(label, False, f"django 未就绪: {err}", duration_ms=_ms(start))
    from django.conf import settings

    cache = settings.CACHES.get("default", {})
    backend = (cache.get("BACKEND") or "").lower()
    location = cache.get("LOCATION")
    if "redis" not in backend or not location:
        return CheckResult(label, True, "未启用 Redis 缓存（内存缓存），跳过",
                           skipped=True, duration_ms=_ms(start))
    return check_redis_url(location, label=label, _start=start)


def check_redis_url(url: str, label: str = "redis", _start: Optional[float] = None) -> CheckResult:
    """显式 Redis URL ping（供 AI_STUDIO_CHANNEL_REDIS 等独立地址使用）。"""
    start = _start if _start is not None else time.monotonic()
    if not url:
        return CheckResult(label, True, "未配置 Redis 地址，跳过", skipped=True, duration_ms=_ms(start))
    try:
        import redis

        r = redis.Redis.from_url(
            url, socket_connect_timeout=min(_CHECK_TIMEOUT, 3.0),
            socket_timeout=_CHECK_TIMEOUT, decode_responses=True,
        )
        r.ping()
        return CheckResult(label, True, url.split("@")[-1], duration_ms=_ms(start))
    except Exception as exc:
        return CheckResult(label, False, f"{type(exc).__name__}: {exc}", duration_ms=_ms(start))


def check_env_not_default(name: str, default_substrings: List[str], label: str = "env") -> CheckResult:
    """检查环境变量是否已设置且非默认/不安全占位值。未设置则跳过（settings 可能有默认）。"""
    start = time.monotonic()
    val = os.environ.get(name, "")
    if not val:
        return CheckResult(label, True, f"{name} 未在环境变量设置（用 settings 默认），跳过",
                           skipped=True, duration_ms=_ms(start))
    if any(s in val for s in default_substrings):
        return CheckResult(label, False, f"{name} 仍为默认/不安全占位值",
                           duration_ms=_ms(start))
    return CheckResult(label, True, f"{name} 已配置", duration_ms=_ms(start))


def check_env_required(required: Dict[str, str], label: str = "env") -> CheckResult:
    """必需环境变量非空检查。required = {变量名: 说明}。"""
    start = time.monotonic()
    missing = [f"{k}({v})" for k, v in required.items() if not os.environ.get(k, "")]
    if missing:
        return CheckResult(label, False, "缺失: " + ", ".join(missing), duration_ms=_ms(start))
    return CheckResult(label, True, f"{len(required)} 项必需配置齐备", duration_ms=_ms(start))


# ---------------------------------------------------------------
# 各服务默认检查集
# ---------------------------------------------------------------

def _notice_channel_check(label: str = "channels") -> CheckResult:
    """通知渠道凭证检查：列出已配置渠道；全部未配置时 WARN（不阻断）。"""
    start = time.monotonic()
    channels = {
        "email": os.environ.get("EMAIL_SEND_LIST", ""),
        "dingtalk": os.environ.get("DINGTALK_WEBHOOK", ""),
        "feishu": os.environ.get("FEISHU_WEBHOOK", ""),
        "wechat": os.environ.get("WECHAT_WEBHOOK", ""),
    }
    configured = [k for k, v in channels.items() if v]
    if not configured:
        return CheckResult(label, False, "未配置任何渠道凭证（DINGTALK/FEISHU/WECHAT_WEBHOOK 或 EMAIL_*），通知将无法外发",
                           duration_ms=_ms(start))
    return CheckResult(label, True, "已配置渠道: " + ", ".join(configured), duration_ms=_ms(start))


def default_checks(service: str = "") -> List[CheckFn]:
    """按服务返回默认检查集。"""
    svc = service.split("_")[-1] if service else ""
    if service.startswith("celery"):
        svc = service.replace("celery_", "")

    if svc == "notice":
        return [
            check_database,
            check_broker,
            check_redis_from_cache,
            _notice_channel_check,
        ]
    if svc == "ai_studio":
        def _ai_redis() -> CheckResult:
            return check_redis_url(os.environ.get("AI_STUDIO_CHANNEL_REDIS", ""),
                                   label="channel_redis")
        return [
            check_database,
            check_broker,
            check_redis_from_cache,
            _ai_redis,
            lambda: check_env_not_default("JWT_SIGNING_KEY", ["change-me", "dev-", "insecure"]),
        ]
    # main / celery_main / 未知 → 主平台检查集
    return [
        check_database,
        check_redis_from_cache,
        check_broker,
        lambda: check_env_not_default("JWT_SIGNING_KEY", ["change-me", "dev-", "insecure"]),
    ]


# ---------------------------------------------------------------
# 启动检查主入口
# ---------------------------------------------------------------

def _ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


def run_startup_checks(service: str = "", checks: Optional[List[CheckFn]] = None,
                       fatal: Optional[bool] = None) -> bool:
    """
    执行启动检查。

    Returns:
        True 全部通过（或全部跳过）；False 存在失败项。
    失败策略:
        fatal=True（或 STARTUP_CHECKS_FATAL=1）时失败即 sys.exit(1)；
        默认仅 WARN 不阻断启动。
    """
    if os.environ.get("STARTUP_CHECKS_ENABLED", "1") != "1":
        _log(f"[startup] {service or 'service'}: 启动检查已禁用 (STARTUP_CHECKS_ENABLED=0)")
        return True

    if checks is None:
        checks = default_checks(service)

    # Django settings 未就绪时无法执行依赖检查：整体跳过并 WARN，不误报 FAIL
    django_err = _ensure_django()
    if django_err:
        _log(f"[startup] {service or 'service'}: Django 环境未就绪（{django_err}），跳过启动检查", "warning")
        return True

    _log(f"[startup] {service or 'service'}: 开始启动检查（{len(checks)} 项）...")
    results: List[CheckResult] = []
    for fn in checks:
        name = getattr(fn, "__name__", "check")
        try:
            r = fn()
        except Exception as exc:  # 检查器自身异常不应让启动崩掉
            r = CheckResult(name, False, f"检查器异常: {type(exc).__name__}: {exc}")
        results.append(r)
        _log(f"[startup] {r.line()}")

    failed = [r for r in results if not r.ok and not r.skipped]
    skipped = [r for r in results if r.skipped]
    all_ok = not failed

    if all_ok:
        _log(f"[startup] {service or 'service'}: 启动检查全部通过 "
             f"({len(results)} 项, 跳过 {len(skipped)})")
    else:
        for r in failed:
            _log(f"[startup] {service or 'service'}: 依赖检查失败 → {r.name}: {r.detail}", "error")
        _log(f"[startup] {service or 'service'}: 启动检查发现 {len(failed)} 项失败"
             f"（服务可降级运行；设 STARTUP_CHECKS_FATAL=1 可改为失败即退出）", "warning")

    if fatal is None:
        fatal = os.environ.get("STARTUP_CHECKS_FATAL", "0") == "1"
    if not all_ok and fatal:
        _log(f"[startup] {service or 'service'}: STARTUP_CHECKS_FATAL=1，退出进程", "error")
        sys.exit(1)

    return all_ok


# ---------------------------------------------------------------
# 启动横幅
# ---------------------------------------------------------------

def _term_supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def emit_startup_banner(key: str = "", extra: Optional[str] = None) -> None:
    """服务启动横幅：settings 加载前即可安全调用（纯 print + 可选 ANSI）。"""
    name = _SERVICE_NAMES.get(key, key or "service")
    color = "\x1b[1;36m" if _term_supports_color() else ""
    reset = "\x1b[0m" if color else ""

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    try:
        import django
        dj_ver = django.get_version()
    except Exception:
        dj_ver = "-"

    lines = [
        f"{color}============================================================{reset}",
        f"{color}  SERVICE START: {key} — {name}{reset}",
        f"  时间   : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"  环境   : {os.environ.get('APP_ENV', os.environ.get('ENV_TYPE', 'DEV'))} "
        f"| WORKER: {os.environ.get('WORKER_TYPE', 'web')}",
        f"  版本   : Python {py_ver} | Django {dj_ver}",
        f"  PID    : {os.getpid()} | host: {socket.gethostname()}",
    ]
    if extra:
        lines.append(f"  extra  : {extra}")
    lines.append(f"{color}============================================================{reset}")

    print("\n".join(lines), flush=True)


def startup_boot(service: str, extra: Optional[str] = None,
                 checks: Optional[List[CheckFn]] = None,
                 fatal: Optional[bool] = None) -> bool:
    """横幅 + 启动检查 一步到位（各服务入口推荐用法）。"""
    emit_startup_banner(service, extra=extra)
    return run_startup_checks(service=service, checks=checks, fatal=fatal)
