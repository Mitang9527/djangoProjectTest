import time
from functools import wraps
from typing import Text
from datetime import datetime, timedelta


def count_milliseconds(access_start, access_end):
    """
    计算时间
    :return:
    """
    access_start = datetime.now()
    access_end = datetime.now()
    access_delta = (access_end - access_start).seconds * 1000
    return access_delta

def timestamp():
    """
    返回时间戳
    """
    timestamp_ms = int(time.time() * 1000)
    return timestamp_ms

def timestamp_conversion(time_str: Text) -> int:
    """
    时间戳转换，将日期格式转换成时间戳
    :param time_str: 时间
    :return:
    """

    try:
        datetime_format = datetime.strptime(str(time_str), "%Y-%m-%d %H:%M:%S")
        timestamp = int(
            time.mktime(datetime_format.timetuple()) * 1000.0
            + datetime_format.microsecond / 1000.0
        )
        return timestamp
    except ValueError as exc:
        raise ValueError('日期格式错误, 需要传入得格式为 "%Y-%m-%d %H:%M:%S" ') from exc

def time_conversion(time_num: int):
    """
    时间戳转换成日期
    :param time_num:
    :return:
    """
    if isinstance(time_num, int):
        time_stamp = float(time_num / 1000)
        time_array = time.localtime(time_stamp)
        other_style_time = time.strftime("%Y-%m-%d %H:%M:%S", time_array)
        return other_style_time

def now_time():
    """
    获取当前时间, 日期格式: 2021-12-11 12:39:25
    :return:
    """
    localtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return localtime

def nowtime():
    """
    获取当前时间, 时间格式: 12:39:25
    :return:
    """
    localtime = time.strftime("%H:%M:%S", time.localtime())
    return localtime

def now_time_day():
    """
    获取当前时间, 日期格式: 2021-12-11
    :return:
    """
    localtime = time.strftime("%Y_%m_%d", time.localtime())
    return localtime

def datetime_strftime():
    """
        获取当前时间, 日期格式: 20250123_172225
        :return:
    """
    datetime_strftime = datetime.now().strftime("%Y%m%d_%H%M%S")
    return datetime_strftime

def tomorrow_time_day():
    """
    获取明天的日期，日期格式: YYYY-MM-DD
    :return:
    """
    # 获取当前日期
    today = datetime.now()
    # 计算明天的日期
    tomorrow = today + timedelta(days=1)
    # 格式化日期
    return tomorrow.strftime("%Y-%m-%d")

def get_time_for_min(minute: int) -> int:
    """
    获取几分钟后的时间戳
    @param minute: 分钟
    @return: N分钟后的时间戳
    """
    return int(time.time() + 60 * minute) * 1000

def get_now_time() -> int:
    """
    获取当前时间戳, 整形
    @return: 当前时间戳
    """
    return int(time.time()) * 1000

def timeit(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"{func.__name__}耗时: {(end_time - start_time):.3f} 秒")
        return result
    return wrapper


def timer(logger_func=None):
    """
    一个更灵活的计时装饰器，可以接收一个日志函数作为参数。

    Args:
        logger_func (callable, optional): 用于输出日志的函数。默认为 print。
        lambda msg: print(f"[TIMING] {msg}"):传递一个 lambda 函数，将日志格式化后输出
        lambda msg: log_file.write(msg + "\n") :传递一个文件对象的 write 方法，将日志写入文件
    """
    if logger_func is None:
        logger_func = print

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            end_time = time.perf_counter()

            execution_time = end_time - start_time

            # 使用传入的日志函数来输出时间信息
            log_message = f"函数 '{func.__name__}' 执行了 {execution_time:.6f} 秒"
            logger_func(log_message)

            return result

        return wrapper

    return decorator
