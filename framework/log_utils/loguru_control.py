"""
loguru 日志管理器 — 接管 Django 标准 logging, 支持多 Logger 分离。

12 项优化:
 1. 文件命名用 {time:YYYY-MM-DD} 动态日期 (修复跨天轮转 bug)
 2. enqueue=True 异步写入 (线程安全 + 不阻塞请求)
 3. InterceptHandler 保留原始 logger name
 4. JSON 结构化日志 (生产模式, 适配 ELK/Loki)
 5. Request-ID 集成 (contextualize 全链路追踪)
 6. 异常格式化 (backtrace=True + diagnose)
 7. reconfigure() 支持 (运行时动态重配置)
 8. 控制台/文件分级 (控制台 DEBUG, 文件 INFO)
 9. retention 细化 (app/celery/api 14 天, error 30 天, 按子目录隔离)
10. Sentry event_id 关联 (ERROR+ 自动转发, request_id tag 贯穿)
11. 日志采样 (高频同源日志限流, ERROR+ 不限)
12. filter 提取为方法 (消除内联 lambda)

日志文件 (logs/ 子目录):
    logs/app/{time:YYYY-MM-DD}.log      — 通用应用日志
    logs/celery/{time:YYYY-MM-DD}.log   — Celery 任务日志
    logs/api/{time:YYYY-MM-DD}.log      — API 请求日志
    logs/error/{time:YYYY-MM-DD}.log    — 所有 ERROR+ (跨域聚合)

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

# ---------------------------------------------------------------
# 日志源标识 (用于 filter 路由)
# ---------------------------------------------------------------

SOURCE_APP    = "app"
SOURCE_CELERY = "celery"
SOURCE_API    = "api"

# 绑定专用 logger
celery_logger = logger.bind(source=SOURCE_CELERY)
api_logger    = logger.bind(source=SOURCE_API)


# ---------------------------------------------------------------
# #11 — 日志采样器
# ---------------------------------------------------------------

class RateLimitFilter:
    """
    日志采样器 — 同一 source:message 在 time_window 秒内只记录 max_count 次。

    ERROR+ 始终放行，不做采样。
    用于高频日志 (心跳、WebSocket ping、轮询等) 防止日志爆炸。

    用法:
        # 作为 sink filter
        logger.add("noisy.log", filter=RateLimitFilter(max_count=5, time_window=60))

        # 每个文件 sink 独立实例 (各自计数)
        logger.add("app.log", filter=RateLimitFilter())
    """

    def __init__(self, max_count: int = 50, time_window: float = 60.0):
        self.max_count = max_count
        self.time_window = time_window
        self._counts: dict = defaultdict(list)
        self._lock = threading.Lock()

    def __call__(self, record) -> bool:
        """loguru filter: 返回 True 表示允许记录"""
        # ERROR+ 始终记录
        if record["level"].no >= logger.level("ERROR").no:
            return True

        key = f"{record['name']}:{record['function']}:{record['message'][:100]}"
        now = time.monotonic()

        with self._lock:
            timestamps = self._counts[key]
            # 清理过期时间戳
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


# ---------------------------------------------------------------
# #3 — InterceptHandler (保留原始 logger name)
# ---------------------------------------------------------------

class InterceptHandler(logging.Handler):
    """将 Python 标准库的 logging 消息重定向到 loguru，保留原始 logger name。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # #3 — 跳过 logging 模块帧, 定位到真正的调用者
        #       sys._getframe(1) = emit() 的调用者 (通常在 logging 模块内)
        #       逐帧向上跳过所有 logging 模块的内部帧, 直到到达用户代码
        try:
            frame = sys._getframe(1)
        except (ValueError, AttributeError):
            frame = None
        depth = 1
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # 保留原始 logger name (Django/uvicorn/gunicorn 等)
        logger.bind(logger_name=record.name).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


# ---------------------------------------------------------------
# #10 — Sentry 集成 (ERROR+ 自动转发)
# ---------------------------------------------------------------

_sentry_enabled = False


def mark_sentry_enabled():
    """通知 loguru Sentry 已初始化 (由 sentry_init 调用)"""
    global _sentry_enabled
    _sentry_enabled = True


def _sentry_sink(message):
    """
    Loguru sink — 将 ERROR+ 日志转发到 Sentry SDK。

    - 自动携带 request_id tag (贯穿 Sentry 事件)
    - 自动携带 source tag (区分日志来源)
    - 异常自动 capture_exception, 消息自动 capture_message
    - Sentry 未初始化时静默跳过
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


# ---------------------------------------------------------------
# #4 — JSON 序列化 sink (生产模式, ELK/Loki 兼容)
# ---------------------------------------------------------------

def _json_serializer(message):
    """
    自定义 JSON 序列化 — 输出到 stderr (供容器日志驱动采集)。

    字段: timestamp, level, logger, function, line, message,
          source, request_id, exception (type/value), extra
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

    # 异常信息
    if record["exception"]:
        exc = record["exception"]
        log_entry["exception"] = {
            "type":  exc.type.__name__ if exc.type else "Unknown",
            "value": str(exc.value) if exc.value else "",
        }

    # 额外字段 (排除已提取的)
    known_keys = {"source", "request_id", "logger_name"}
    extra_keys = set(record["extra"].keys()) - known_keys
    if extra_keys:
        log_entry["extra"] = {
            k: str(v) for k, v in record["extra"].items() if k in extra_keys
        }

    print(json.dumps(log_entry, ensure_ascii=False, default=str), file=sys.stderr)


# ---------------------------------------------------------------
# LogManager — 统一初始化入口
# ---------------------------------------------------------------

class LogManager:
    """
    日志管理器 — 线程安全单例，支持 reconfigure。

    优化清单:
      1.  文件命名用 {time:YYYY-MM-DD} 动态日期
      2.  enqueue=True 异步写入
      3.  InterceptHandler 保留 logger name
      4.  JSON 结构化日志 (非 DEBUG)
      5.  Request-ID 集成 (configure extra 默认值)
      6.  backtrace/diagnose 异常格式化
      7.  reconfigure() 动态重配置
      8.  控制台/文件分级
      9.  retention 细化
      10. Sentry sink (ERROR+ 转发)
      11. 高频日志采样
      12. filter 方法化
    """

    _initialized = False
    _sink_ids: list = []
    _lock = threading.Lock()

    # ---- #12 — filter 工厂方法 ----

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

    # ---- 初始化 ----

    def __init__(self, log_dir: str = None, level: str = "INFO",
                 json_output: Optional[bool] = None, debug: Optional[bool] = None):
        """
        初始化日志系统。

        Args:
            log_dir:      日志目录, 默认 logs/
            level:        文件日志级别 (控制台始终 DEBUG if debug=True)
            json_output:  是否输出 JSON 日志 (None=自动: 非 debug 时开启)
            debug:        是否 DEBUG 模式 (None=从 level 推断: level=="DEBUG" 则 True)
        """
        with LogManager._lock:
            if LogManager._initialized:
                return
            self._setup(log_dir, level, json_output, debug)
            LogManager._initialized = True

    @classmethod
    def reconfigure(cls, log_dir: str = None, level: str = "INFO",
                    json_output: Optional[bool] = None, debug: Optional[bool] = None):
        """
        #7 — 重新配置日志系统。

        移除所有现有 sink，重新初始化。
        可用于运行时动态调整日志级别。

        用法:
            from framework.log_utils import LogManager
            LogManager.reconfigure(level="DEBUG", debug=True)
        """
        with cls._lock:
            # 移除所有现有 sink
            for sink_id in cls._sink_ids:
                try:
                    logger.remove(sink_id)
                except Exception:
                    pass
            cls._sink_ids.clear()
            cls._initialized = False

            instance = cls.__new__(cls)
            instance._setup(log_dir, level, json_output, debug)
            cls._initialized = True

    # ---- 核心初始化 ----

    def _setup(self, log_dir: str, level: str, json_output: Optional[bool],
               debug: Optional[bool]):
        """核心初始化逻辑 (被 __init__ 和 reconfigure 共用)"""
        # 推断 debug 模式
        if debug is None:
            debug = level.upper() == "DEBUG"

        # ---- #8 — 分级 ----
        console_level = "DEBUG" if debug else "INFO"
        file_level = level.upper()
        if file_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            file_level = "INFO"

        # ---- #4 — JSON 自动开启 ----
        if json_output is None:
            json_output = not debug

        # ---- 日志目录 ----
        if log_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(current_dir)), "logs"
            )
        os.makedirs(log_dir, exist_ok=True)

        # ---- 子目录 (app / celery / api / error) ----
        for sub in ("app", "celery", "api", "error"):
            os.makedirs(os.path.join(log_dir, sub), exist_ok=True)

        # ---- #5 — 设置默认 extra (request_id, source, logger_name) ----
        logger.configure(extra={
            "request_id": "-",
            "source": SOURCE_APP,
            "logger_name": "-",
        })

        # ---- 0. 清除所有现有 handler ----
        try:
            logger.remove()
        except Exception:
            pass
        LogManager._sink_ids.clear()

        # ---- 1. Sentry sink (最先添加, ERROR+ 转发) ---- (#10)
        sentry_id = logger.add(_sentry_sink, level="ERROR")
        LogManager._sink_ids.append(sentry_id)

        # ---- 2. 控制台输出 ---- (#8 分级, #5 request_id)
        console_fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<blue>{extra[request_id]}</blue> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        console_id = logger.add(
            sys.stdout,
            level=console_level,
            format=console_fmt,
            colorize=True,
        )
        LogManager._sink_ids.append(console_id)

        # ---- 公共文件格式 ---- (#5 包含 request_id)
        file_fmt = (
            "{time:YYYY-MM-DD HH:mm:ss} | {level} | "
            "{extra[request_id]} | "
            "{name}:{function}:{line} | {message}"
        )

        # ---- 3. JSON 结构化日志 (生产模式) ---- (#4)
        if json_output:
            json_id = logger.add(
                _json_serializer,
                level=file_level,
                serialize=False,
            )
            LogManager._sink_ids.append(json_id)

        # ---- 4. app.log — 通用日志 ---- (#1, #2, #9, #11, #12)
        app_id = logger.add(
            os.path.join(log_dir, "app", "{time:YYYY-MM-DD}.log"),  # #1 动态日期
            rotation="00:00",
            retention="14 days",   # #9 细化
            compression="gz",
            level=file_level,
            format=file_fmt,
            encoding="utf-8",
            enqueue=True,          # #2 异步写入
            filter=self._make_exclusion_filter(SOURCE_CELERY, SOURCE_API),  # #12
        )
        LogManager._sink_ids.append(app_id)

        # ---- 5. celery.log ---- (#1, #2, #9, #12)
        celery_id = logger.add(
            os.path.join(log_dir, "celery", "{time:YYYY-MM-DD}.log"),  # #1
            rotation="00:00",
            retention="14 days",   # #9
            compression="gz",
            level=file_level,
            format=file_fmt,
            encoding="utf-8",
            enqueue=True,          # #2
            filter=self._make_source_filter(SOURCE_CELERY),  # #12
        )
        LogManager._sink_ids.append(celery_id)

        # ---- 6. api.log ---- (#1, #2, #9, #12)
        api_id = logger.add(
            os.path.join(log_dir, "api", "{time:YYYY-MM-DD}.log"),  # #1
            rotation="00:00",
            retention="14 days",   # #9
            compression="gz",
            level=file_level,
            format=file_fmt,
            encoding="utf-8",
            enqueue=True,          # #2
            filter=self._make_source_filter(SOURCE_API),  # #12
        )
        LogManager._sink_ids.append(api_id)

        # ---- 7. error.log — ERROR+ 跨域聚合 ---- (#1, #2, #6, #9)
        error_id = logger.add(
            os.path.join(log_dir, "error", "{time:YYYY-MM-DD}.log"),  # #1
            rotation="00:00",
            retention="30 days",   # #9
            compression="gz",
            level="ERROR",
            format=file_fmt,
            encoding="utf-8",
            enqueue=True,          # #2
            backtrace=True,        # #6 完整调用栈
            diagnose=debug,        # #6 DEBUG 时显示变量值 (生产关闭避免泄露)
        )
        LogManager._sink_ids.append(error_id)

        # ---- 7.5 ERROR 突增计数 sink ---- (#13 监控: 滑动窗口统计 ERROR+)
        try:
            from framework.log_utils.error_spike import _error_spike_sink
            error_spike_sink_id = logger.add(_error_spike_sink, level="ERROR")
            LogManager._sink_ids.append(error_spike_sink_id)
        except Exception:
            pass

        # ---- 8. 自定义级别 ----
        try:
            logger.level("FATAL", no=60, color="<red>", icon="!!!")
        except Exception:
            pass

        # ---- 9. 接管标准 logging ---- (#3)
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
