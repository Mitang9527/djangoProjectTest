"""
通用装饰器模块
包含常用的装饰器工具函数
"""
import time
from typing import Optional, Callable, Any, Tuple
from collections import defaultdict
from loguru import logger
from functools import wraps



def capture_exceptions(
    func: Optional[Callable] = None,
    *,
    reraise: bool = True,
    log_message: str = "An exception occurred",
    logger_obj: Any = logger,
):
    """
    异常捕获装饰器
    捕获函数执行时的异常，记录日志
    
    Args:
        func: 被装饰的函数
        reraise: 是否重新抛出异常（默认 True）
        log_message: 异常日志前缀信息
        logger_obj: 日志对象（默认使用 loguru logger）
    """
    if func is None:
        def decorator(real_func: Callable) -> Callable:
            @wraps(real_func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return real_func(*args, **kwargs)
                except Exception:
                    logger_obj.exception(log_message)
                    if reraise:
                        raise
                    return None
            return wrapper
        return decorator

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception:
            logger_obj.exception(log_message)
            if reraise:
                raise
            return None
    return wrapper


def execution_duration(
    threshold_ms: int,
    *,
    logger_obj: Any = logger,
    log_level: str = "warning",
) -> Callable:
    """
    统计函数执行时间装饰器

    超过阈值时记录日志。
    即使函数抛出异常，也会统计执行时间。

    Args:
        threshold_ms: 阈值（毫秒）
        logger_obj: 日志对象
        log_level: 日志级别
    """

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            has_error = False

            try:
                return func(*args, **kwargs)

            except Exception:
                has_error = True
                raise

            finally:
                duration_ms = (time.perf_counter() - start) * 1000

                if duration_ms > threshold_ms:
                    status = "异常" if has_error else "正常"

                    log_func = getattr(
                        logger_obj,
                        log_level,
                        logger_obj.warning,
                    )

                    log_func(
                        f"[{status}] "
                        f"{func.__module__}.{func.__name__} "
                        f"执行耗时 {duration_ms:.2f}ms "
                        f"(阈值 {threshold_ms}ms)"
                    )

        return wrapper

    return decorator


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: Tuple[Exception, ...] = (Exception,),
    logger_obj: Any = logger,
):
    """
    自动重试装饰器
    
    Args:
        max_attempts: 最大重试次数（默认 3 次）
        delay: 重试间隔（秒，默认 1 秒）
        exceptions: 需要重试的异常类型
        logger_obj: 日志对象（默认使用 loguru logger）
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempts += 1
                    if attempts == max_attempts:
                        logger_obj.error(f"{func.__name__} 重试 {max_attempts} 次后失败: {e}")
                        raise
                    logger_obj.warning(f"{func.__name__} 尝试 {attempts}/{max_attempts}，{delay}秒后重试: {e}")
                    time.sleep(delay)
        return wrapper
    return decorator


def cache(ttl_seconds: int = 3600):
    """
    带过期时间的内存缓存装饰器
    
    Args:
        ttl_seconds: 缓存过期时间（秒，默认 3600 秒）
    """
    def decorator(func: Callable) -> Callable:
        _cache = {}
        _cache_times = {}
        
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = str(args) + str(sorted(kwargs.items()))
            now = time.time()
            
            if key in _cache and (now - _cache_times[key]) < ttl_seconds:
                return _cache[key]
            
            result = func(*args, **kwargs)
            _cache[key] = result
            _cache_times[key] = now
            return result
        return wrapper
    return decorator


def singleton(cls):
    """
    单例模式装饰器
    确保一个类只有一个实例
    """
    instances = {}
    
    @wraps(cls)
    def get_instance(*args: Any, **kwargs: Any) -> Any:
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    return get_instance


def log(level: str = "INFO", logger_obj: Any = logger):
    """
    记录函数调用和返回值的装饰器
    
    Args:
        level: 日志级别（默认 INFO）
        logger_obj: 日志对象（默认使用 loguru logger）
    """
    def decorator(func: Callable) -> Callable:
        log_func = getattr(logger_obj, level.lower(), logger.info)
        
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log_func(f"调用 {func.__name__}，参数: args={args}, kwargs={kwargs}")
            
            result = func(*args, **kwargs)
            
            log_func(f"{func.__name__} 返回: {result}")
            return result
        return wrapper
    return decorator


def rate_limit(limit: int = 10, interval: int = 60,):
    """
    限制调用频率的装饰器
    
    Args:
        limit: 时间窗口内最大调用次数
        interval: 时间窗口（秒）
    """
    def decorator(func: Callable) -> Callable:
        call_history = []
        
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            now = time.time()
            # 清理过期记录
            call_history[:] = [t for t in call_history if now - t < interval]
            
            if len(call_history) >= limit:
                error_msg = f"频率限制: {func.__name__} 在 {interval}秒内最多调用 {limit}次"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            call_history.append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator


# 性能统计
_performance_data = defaultdict(list)

def measure_performance(func: Callable) -> Callable:
    """
    记录和统计函数调用性能的装饰器
    
    使用 get_performance_stats() 获取统计数据
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start
        
        _performance_data[func.__name__].append(duration)
        
        return result
    return wrapper


def get_performance_stats():
    """
    获取所有用 @measure_performance 装饰的函数的性能统计数据
    """
    stats = {}
    for func_name, times in _performance_data.items():
        stats[func_name] = {
            "calls": len(times),
            "avg": sum(times) / len(times) if times else 0,
            "min": min(times) if times else 0,
            "max": max(times) if times else 0,
            "total": sum(times) if times else 0
        }
    return stats


def print_performance_stats(logger_obj: Any = logger):
    """
    打印性能统计数据
    """
    stats = get_performance_stats()
    if not stats:
        logger_obj.info("没有性能统计数据")
        return
    
    logger_obj.info("=" * 60)
    logger_obj.info("性能统计数据")
    logger_obj.info("=" * 60)
    for func_name, data in stats.items():
        logger_obj.info(
            f"{func_name:20s} | 调用次数: {data['calls']:4d} | "
            f"平均: {data['avg']:.4f}s | 最小: {data['min']:.4f}s | "
            f"最大: {data['max']:.4f}s | 总计: {data['total']:.4f}s"
        )
    logger_obj.info("=" * 60)
