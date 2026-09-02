"""
loguru 日志管理器 — 接管 Django 标准 logging，支持多 Logger 分离。
特性: 动态日期命名、enqueue 异步、InterceptHandler 保留 logger name、JSON 结构化(生产)、
Request-ID 全链路、retention 细化(app/celery/api 14 天 / error 30 天)、Sentry ERROR+ 转发、日志采样、OSC8 超链接跳转。

用法:
    from loguru import logger                    # 默认 → app log
    from framework.log_utils import celery_logger     # → celery log
    from framework.log_utils import api_logger        # → api log
    from framework.log_utils import LogManager        # 初始化入口
    from framework.log_utils import RateLimitFilter   # 日志采样器
"""

import os
import sys
import json
import time
import logging
import threading
from collections import defaultdict
from typing import Optional

from loguru import logger

# 日志源标识 (用于 filter 路由)
SOURCE_APP    = "app"
SOURCE_CELERY = "celery"
SOURCE_API    = "api"

celery_logger = logger.bind(source=SOURCE_CELERY)
api_logger    = logger.bind(source=SOURCE_API)


# #11 — 日志采样器

class RateLimitFilter:
    """
    日志采样器 — 同一 source:message 在 time_window 秒内只记录 max_count 次；ERROR+ 始终放行。
    用于高频日志(心跳/WebSocket ping/轮询)防日志爆炸。
    用法: logger.add("noisy.log", filter=RateLimitFilter(max_count=5, time_window=60))；每个文件 sink 独立实例各自计数。
    """

    def __init__(self, max_count: int = 50, time_window: float = 60.0):
        self.max_count = max_count
        self.time_window = time_window
        self._counts: dict = defaultdict(list)
        self._lock = threading.Lock()

    def __call__(self, record) -> bool:
        """loguru filter: 返回 True 表示允许记录"""
        if record["level"].no >= logger.level("ERROR").no:
            return True

        key = f"{record['name']}:{record['function']}:{record['message'][:100]}"
        now = time.monotonic()

        with self._lock:
            timestamps = self._counts[key]
            cutoff = now - self.time_window
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)

            if len(timestamps) >= self.max_count:
                return False

            timestamps.append(now)
            return True

    def reset(self):
        """重置所有计数器"""
        with self._lock:
            self._counts.clear()


# #3 — InterceptHandler (保留原始 logger name)

class InterceptHandler(logging.Handler):
    """将 Python 标准库的 logging 消息重定向到 loguru，保留原始 logger name。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # #3 — 跳过 logging 模块内部帧 (sys._getframe 逐帧上溯)，定位到真正的调用者
        try:
            frame = sys._getframe(1)
        except (ValueError, AttributeError):
            frame = None
        depth = 1
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(logger_name=record.name).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


# #10 — Sentry 集成 (ERROR+ 自动转发)

_sentry_enabled = False


def mark_sentry_enabled():
    """通知 loguru Sentry 已初始化 (由 sentry_init 调用)"""
    global _sentry_enabled
    _sentry_enabled = True


def _sentry_sink(message):
    """
    Loguru sink — 将 ERROR+ 日志转发 Sentry SDK；自动携带 request_id/source tag，
    异常 capture_exception、消息 capture_message；Sentry 未初始化时静默跳过。
    """
    if not _sentry_enabled:
        return

    try:
        import sentry_sdk
        client = sentry_sdk.Hub.current.client
        if client is None:
            return

        record = message.record
        level_name = record["level"].name

        if level_name not in ("ERROR", "CRITICAL", "FATAL"):
            return

        tags = {
            "request_id": record["extra"].get("request_id", "-"),
            "source": record["extra"].get("source", SOURCE_APP),
        }

        with sentry_sdk.push_scope() as scope:
            scope.set_tags(tags)
            scope.set_extra("logger_name", record["name"])
            scope.set_extra("function", record["function"])
            scope.set_extra("line", record["line"])

            if record["exception"]:
                sentry_sdk.capture_exception(record["exception"])
            else:
                sentry_sdk.capture_message(
                    record["message"], level=level_name.lower()
                )
    except Exception:
        pass  # 日志 sink 不应抛出异常


# #4 — JSON 序列化 sink (生产模式, ELK/Loki 兼容)

def _json_serializer(message):
    """
    自定义 JSON 序列化 — 输出到 stderr (供容器日志驱动采集)。
    字段: timestamp, level, logger, function, line, message, source, request_id, exception(type/value), extra
    """
    record = message.record
    log_entry = {
        "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        "level":      record["level"].name,
        "logger":     record["name"],
        "logger_name": record["extra"].get("logger_name", "-"),
        "function":   record["function"],
        "line":       record["line"],
        "message":    record["message"],
        "source":     record["extra"].get("source", SOURCE_APP),
        "request_id": record["extra"].get("request_id", "-"),
    }

    if record["exception"]:
        exc = record["exception"]
        log_entry["exception"] = {
            "type":  exc.type.__name__ if exc.type else "Unknown",
            "value": str(exc.value) if exc.value else "",
        }

    known_keys = {"source", "request_id", "logger_name"}
    extra_keys = set(record["extra"].keys()) - known_keys
    if extra_keys:
        log_entry["extra"] = {
            k: str(v) for k, v in record["extra"].items() if k in extra_keys
        }

    print(json.dumps(log_entry, ensure_ascii=False, default=str), file=sys.stderr)


# #14 — 控制台超链接跳转 (OSC 8 hyperlinks)

# loguru 默认 level 颜色 (raw ANSI), 用于自绘控制台格式
_LEVEL_ANSI = {
    "TRACE":    "\x1b[36;1m",   # <cyan><bold>
    "DEBUG":    "\x1b[34;1m",   # <blue><bold>
    "INFO":     "\x1b[1m",      # <bold>
    "SUCCESS":  "\x1b[32;1m",   # <green><bold>
    "WARNING":  "\x1b[33;1m",   # <yellow><bold>
    "ERROR":    "\x1b[31;1m",   # <red><bold>
    "CRITICAL": "\x1b[91;1m",   # <RED><bold>
    "FATAL":    "\x1b[91;1m",   # 自定义 FATAL
}
_ANSI_RESET = "\x1b[0m"


def _osc8_link(url: str, text: str) -> str:
    """生成 OSC 8 超链接 (file://... 等), 支持点击跳转的终端可点击。"""
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def _normalize_file_uri(path: str, line: int) -> str:
    """将绝对路径规范为 file:// URI，兼容 Windows 盘符 (D:\\x -> file:///D:/x)。"""
    p = path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/" + p
    return f"file://{p}:{line}"


def _escape_markup(s: str) -> str:
    """转义 loguru Colorizer 标记: 仅 '<' 会被当作颜色标签解析，转义为 '\\<' (渲染后仍为 '<')；'>' 单独无歧义，不必转义。OSC8/ANSI 的 ESC(\\x1b) 不受影响。"""
    return s.replace("<", r"\<")


def _console_supports_hyperlinks() -> bool:
    """检测 stdout 是否为支持 OSC 8 超链接的终端(VSCode/iTerm2>=3.1/Windows Terminal/Konsole/GNOME Terminal/Ghostty/WezTerm)；FORCE_HYPERLINK=1 强制开启(优先于 isatty 检查)。"""
    env = os.environ

    if env.get("FORCE_HYPERLINK"):
        return True
    if not sys.stdout.isatty():
        return False

    if env.get("TERM_PROGRAM") in ("vscode", "ghostty", "WezTerm"):
        return True
    if env.get("TERM_PROGRAM") == "iTerm.app":
        try:
            ver = tuple(int(x) for x in env.get("TERM_PROGRAM_VERSION", "0").split("."))
            return ver >= (3, 1)
        except ValueError:
            return True
    if env.get("WT_SESSION") or env.get("WT_PROFILE_ID"):
        return True
    if env.get("KONSOLE_VERSION"):
        return True
    if env.get("GNOME_TERMINAL_ID") or env.get("GNOME_TERMINAL_SCREEN"):
        return True
    return False


def _make_console_format(hyperlinks: bool):
    """
    生成控制台 sink 的 format 可调用对象。

    ⚠️ 必须用「可调用 format + colorize=False」自行拼装 ANSI/OSC8，不能把 OSC8 直接内联进字符串模板 —
    loguru 的 Colorizer 会把 OSC8 里的 '\\x1b\\\\' 反斜杠误当作转义符而解析失败；且动态内容(函数名 <module>、
    消息正文里的 <tag>)中的 '<' 也会被当成颜色标签报错，可调用 format 中需转义 '<'。hyperlinks=True 且终端支持时 file:line 包裹为可点击超链接。
    """
    def _fmt(record):
        r = record
        t = r["time"].strftime("%Y-%m-%d %H:%M:%S")
        lvl = r["level"].name
        lvl_color = _LEVEL_ANSI.get(lvl, "\x1b[1m")

        time_s = f"\x1b[32m{t}\x1b[0m"                                  # green 时间
        level_s = f"{lvl_color}{lvl:<8}{_ANSI_RESET}"                   # level 配色
        rid = (
            f"\x1b[34m{_escape_log_content(str(r['extra'].get('request_id', '-')))}"
            f"{_ANSI_RESET}"
        )
        # 可见文本须包含真实文件路径 file:line —— PyCharm 等 IDE 运行控制台不识别 OSC8，
        # 但会自动把文本中的"绝对路径:行号"渲染为可点击链接，故可见文本不能仅用模块点分名 name。
        file_loc_text = f"{_escape_log_content(r['file'].path)}:{r['line']}"
        loc_text = (
            f"{_escape_log_content(r['name'])}:"
            f"{_escape_log_content(r['function'])}:"
            f"{r['line']} {file_loc_text}"
        )

        if hyperlinks:
            # URL 同样需转义: 个别环境 file.path 可能为 <string> 等含 '<' 的值
            url = _escape_log_content(_normalize_file_uri(r["file"].path, r["line"]))
            loc = _osc8_link(url, f"\x1b[36m{loc_text}\x1b[0m")
        else:
            loc = f"\x1b[36m{loc_text}\x1b[0m"

        msg = _escape_log_content(r["message"])
        return f"{time_s} | {level_s} | {rid} | {loc} - {msg}\n"

    return _fmt


def _escape_log_content(s: str) -> str:
    """
    转义日志动态内容中的 '<' 与花括号，防止 Loguru 将可调用 format 的输出二次解析为颜色标签/格式字段:
    - '<' → '\\<' : 避免 Colorizer 把 '<module>' 误判为颜色标签 (ValueError)
    - '{' → '{{' / '}' → '}}' : 避免 format_map 把 '{detail}' 当字段 (KeyError)
    """
    return s.replace("<", r"\<").replace("{", "{{").replace("}", "}}")


def _make_file_format():
    """
    文件 sink 格式（可调用，规避 Loguru 对消息体花括号/尖括号的二次解析）。

    ⚠️ Loguru 字符串模板在渲染 `{message}` 时会把消息内容本身当作 format 串重新解析；消息体含未转义
    花括号或 '<...>'（如 DRF 异常 `{'detail': ...}` 的 repr、模块级代码函数名 `<module>`）会抛
    KeyError/ValueError 使日志系统崩溃。改用可调用 format 直接拼接并对动态内容转义，布局与旧 file_fmt 一致。
    """
    def _fmt(record):
        r = record
        t = r["time"].strftime("%Y-%m-%d %H:%M:%S")
        rid = r["extra"].get("request_id", "-")
        name = _escape_log_content(r["name"])
        func = _escape_log_content(r["function"])
        msg = _escape_log_content(r["message"])
        return (
            f"{t} | {r['level'].name} | {rid} | "
            f"{name}:{func}:{r['line']} | {msg}\n"
        )
    return _fmt


# LogManager — 统一初始化入口

class LogManager:
    """
    日志管理器 — 线程安全单例，支持 reconfigure。
    优化清单与模块 docstring 一致（动态日期命名、enqueue 异步、InterceptHandler、JSON、Request-ID、
    backtrace/diagnose、reconfigure、控制台/文件分级、retention 细化、Sentry、采样、filter 方法化、OSC8 跳转）。
    """

    _initialized = False
    _sink_ids: list = []
    _lock = threading.Lock()

    # #12 — filter 工厂方法

    @staticmethod
    def _make_source_filter(source: str):
        """生成日志源过滤器 — 只允许指定 source 的日志"""

        def _filter(record):
            return record["extra"].get("source", SOURCE_APP) == source
        return _filter

    @staticmethod
    def _make_exclusion_filter(*excluded: str):
        """生成排除式过滤器 — 排除指定 source 的日志"""
        def _filter(record):
            return record["extra"].get("source", SOURCE_APP) not in excluded
        return _filter

    def __init__(self, log_dir: str = None, level: str = "INFO",
                 json_output: Optional[bool] = None, debug: Optional[bool] = None,
                 console_hyperlinks: Optional[bool] = None):
        """
        初始化日志系统。
        Args:
            log_dir: 日志目录, 默认 logs/
            level: 文件日志级别 (控制台始终 DEBUG if debug=True)
            json_output: 是否输出 JSON 日志 (None=自动: 非 debug 时开启)
            debug: 是否 DEBUG 模式 (None=从 level 推断: level=="DEBUG" 则 True)
            console_hyperlinks: 控制台 file:line 是否生成可点击超链接 (None=自动探测终端; True/False=强制开/关)
        """
        with LogManager._lock:
            if LogManager._initialized:
                return
            self._setup(log_dir, level, json_output, debug, console_hyperlinks)
            LogManager._initialized = True

    @classmethod
    def reconfigure(cls, log_dir: str = None, level: str = "INFO",
                    json_output: Optional[bool] = None, debug: Optional[bool] = None,
                    console_hyperlinks: Optional[bool] = None):
        """
        #7 — 重新配置日志系统。移除所有现有 sink 并重新初始化，用于运行时动态调整日志级别/超链接开关。
        用法: LogManager.reconfigure(level="DEBUG", debug=True) / LogManager.reconfigure(console_hyperlinks=True)
        """
        with cls._lock:
            for sink_id in cls._sink_ids:
                try:
                    logger.remove(sink_id)
                except Exception:
                    pass
            cls._sink_ids.clear()
            cls._initialized = False

            instance = cls.__new__(cls)
            instance._setup(log_dir, level, json_output, debug, console_hyperlinks)
            cls._initialized = True

    def _setup(self, log_dir: str, level: str, json_output: Optional[bool],
               debug: Optional[bool], console_hyperlinks: Optional[bool] = None):
        """核心初始化逻辑 (被 __init__ 和 reconfigure 共用)"""
        if debug is None:
            debug = level.upper() == "DEBUG"

        # #8 分级
        console_level = "DEBUG" if debug else "INFO"
        file_level = level.upper()
        if file_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            file_level = "INFO"

        # #4 JSON 自动开启
        if json_output is None:
            json_output = not debug

        if log_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(current_dir)), "logs"
            )
        os.makedirs(log_dir, exist_ok=True)

        for sub in ("app", "celery", "api", "error"):
            os.makedirs(os.path.join(log_dir, sub), exist_ok=True)

        # #5 设置默认 extra (request_id, source, logger_name)
        logger.configure(extra={
            "request_id": "-",
            "source": SOURCE_APP,
            "logger_name": "-",
        })

        # 清除所有现有 handler
        try:
            logger.remove()
        except Exception:
            pass
        LogManager._sink_ids.clear()

        # 1. Sentry sink (最先添加, ERROR+ 转发, #10)
        sentry_id = logger.add(_sentry_sink, level="ERROR", format=_make_file_format())
        LogManager._sink_ids.append(sentry_id)

        # 2. 控制台输出 — #14: 自动探测 OSC8 超链接, 可调用 format + colorize=False 自绘 ANSI 避免 Colorizer 解析冲突
        if console_hyperlinks is None:
            console_hyperlinks = _console_supports_hyperlinks()
        console_id = logger.add(
            sys.stdout,
            level=console_level,
            format=_make_console_format(console_hyperlinks),
            colorize=False,
        )
        LogManager._sink_ids.append(console_id)

        # 3. JSON 结构化日志 (生产模式, #4)
        if json_output:
            json_id = logger.add(
                _json_serializer,
                level=file_level,
                serialize=False,
            )
            LogManager._sink_ids.append(json_id)

        # 4. app.log — 通用日志 (#1,#2,#9,#11,#12)
        app_id = logger.add(
            os.path.join(log_dir, "app", "{time:YYYY-MM-DD}.log"),
            rotation="00:00",
            retention="14 days",
            compression="gz",
            level=file_level,
            format=_make_file_format(),
            encoding="utf-8",
            enqueue=True,
            filter=self._make_exclusion_filter(SOURCE_CELERY, SOURCE_API),
        )
        LogManager._sink_ids.append(app_id)

        # 5. celery.log (#1,#2,#9,#12)
        celery_id = logger.add(
            os.path.join(log_dir, "celery", "{time:YYYY-MM-DD}.log"),
            rotation="00:00",
            retention="14 days",
            compression="gz",
            level=file_level,
            format=_make_file_format(),
            encoding="utf-8",
            enqueue=True,
            filter=self._make_source_filter(SOURCE_CELERY),
        )
        LogManager._sink_ids.append(celery_id)

        # 6. api.log (#1,#2,#9,#12)
        api_id = logger.add(
            os.path.join(log_dir, "api", "{time:YYYY-MM-DD}.log"),
            rotation="00:00",
            retention="14 days",
            compression="gz",
            level=file_level,
            format=_make_file_format(),
            encoding="utf-8",
            enqueue=True,
            filter=self._make_source_filter(SOURCE_API),
        )
        LogManager._sink_ids.append(api_id)

        # 7. error.log — ERROR+ 跨域聚合 (#1,#2,#6,#9)
        error_id = logger.add(
            os.path.join(log_dir, "error", "{time:YYYY-MM-DD}.log"),
            rotation="00:00",
            retention="30 days",
            compression="gz",
            level="ERROR",
            format=_make_file_format(),
            encoding="utf-8",
            enqueue=True,
            backtrace=True,
            # #6: DEBUG 时显示变量值，生产关闭避免泄露
            diagnose=debug,
        )
        LogManager._sink_ids.append(error_id)

        # 7.5 ERROR 突增计数 sink (#14: 滑动窗口统计 ERROR+)
        try:
            from framework.log_utils.error_spike import _error_spike_sink
            error_spike_sink_id = logger.add(
                _error_spike_sink, level="ERROR", format=_make_file_format()
            )
            LogManager._sink_ids.append(error_spike_sink_id)
        except Exception:
            pass

        # 8. 自定义级别
        try:
            logger.level("FATAL", no=60, color="<red>", icon="!!!")
        except Exception:
            pass

        # 9. 接管标准 logging (#3)
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
