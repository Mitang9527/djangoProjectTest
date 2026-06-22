import os
import sys
import logging
import warnings
from loguru import logger
from datetime import datetime
import platform


class InterceptHandler(logging.Handler):
    """
    Default handler from loguru docs for importing standard logging messages
    """
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the log message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class LogManager:
    _initialized = False

    def __init__(self, log_dir=None, level="INFO"):
        if LogManager._initialized:
            return

        if log_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(os.path.dirname(os.path.dirname(current_dir)), 'logs')

        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Configure loguru
        log_path = os.path.join(log_dir, datetime.now().strftime("%Y-%m-%d") + ".log")
        
        # 1. Remove ALL existing handlers
        try:
            logger.remove() 
        except Exception:
            pass
        
        # 2. Add console handler FIRST
        logger.add(
            sys.stdout,
            level=level.upper(),
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True,
        )
        
        # 3. Add file handler
        try:
            logger.add(
                log_path,
                rotation="00:00",
                retention="7 days",
                compression="gz",
                level=level.upper(),
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
                enqueue=False,
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[WARNING] 无法添加文件日志处理器: {e}")
        
        # 4. Intercept standard logging
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

        try:
            logger.level("FATAL", no=60, color="<red>", icon="!!!")
        except Exception:
            pass
            
        LogManager._initialized = True

    @staticmethod
    def capture_exceptions(func=None, *, reraise=True, log_message="An exception occurred"):
        """
        [已废弃] 异常捕获装饰器
        请使用 utils.decorators.capture_exceptions 替代
        """
        warnings.warn(
            "LogManager.capture_exceptions is deprecated, use utils.decorators.capture_exceptions instead",
            DeprecationWarning,
            stacklevel=2
        )
        from utils.decorators import capture_exceptions as new_capture_exceptions
        return new_capture_exceptions(func, reraise=reraise, log_message=log_message)

    @staticmethod
    def execution_duration(threshold_ms: int):
        """
        [已废弃] 统计函数执行时间装饰器
        请使用 utils.decorators.execution_duration 替代
        """
        warnings.warn(
            "LogManager.execution_duration is deprecated, use utils.decorators.execution_duration instead",
            DeprecationWarning,
            stacklevel=2
        )
        from utils.decorators import execution_duration as new_execution_duration
        return new_execution_duration(threshold_ms)
