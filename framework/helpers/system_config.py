"""系统信息采集工具。

提供本机 IP、磁盘/内存/CPU 使用率、进程/端口检查、系统信息聚合等能力，供
健康检查、监控看板与系统设置页面使用。
"""
import socket
import subprocess

import requests
import psutil
import platform
from datetime import datetime
from loguru import logger


def get_local_ip():
    """
    获取本机IP地址
    :return:
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_public_ip():
    """
    获取公网IP地址。

    ⚠️ 依赖外部公共服务 httpbin.org，仅用于本地调试（本文件 __main__ 中展示），
    不参与生产链路。请求必须带 timeout，失败时返回 'unknown' 而不是抛异常——
    否则一个不可达的第三方接口会拖垮整个 get_system_info() 调用方。
    """
    try:
        res = requests.get('http://httpbin.org/ip', timeout=5)
        return res.json()['origin']
    except Exception as e:   # noqa: BLE001 - 外部服务不可达属预期情况
        logger.warning(f"获取公网IP失败: {e}")
        return 'unknown'

def get_system_info():
    """
    获取系统资源信息
    :return:
    """
    os_info = f"{platform.system()} {platform.release()}"  # 操作系统
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")  # 最后启动时间

    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count(logical=False)  # 物理核心
    logical_cpu_count = psutil.cpu_count()  # 逻辑核心

    mem = psutil.virtual_memory()
    mem_total = mem.total / (1024 ** 3)  # GB
    mem_used = mem.used / (1024 ** 3)
    mem_percent = mem.percent

    disk = psutil.disk_usage('/')
    disk_total = disk.total / (1024 ** 3)
    disk_used = disk.used / (1024 ** 3)
    disk_percent = disk.percent

    return {
        "cpu": {
            "percent": cpu_percent,
            "physical_cores": cpu_count,
            "logical_cores": logical_cpu_count
        },
        "memory": {
            "total": round(mem_total, 2),
            "used": round(mem_used, 2),
            "percent": mem_percent
        },
        "disk": {
            "total": round(disk_total, 2),
            "used": round(disk_used, 2),
            "percent": disk_percent
        },
        "system": {
            "os": os_info,
            "boot_time": boot_time
        }
    }

def get_jdk_version():
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True, stderr=subprocess.STDOUT)
        return result.stdout.splitlines()[0].strip()
    except Exception as e:
        return f"无法获取 JDK 版本: {e}"


if __name__ == "__main__":
    local_ip = get_local_ip()
    print(f"\n 本机IP地址: \033[1;34m{local_ip}\033[0m")

    public_ip = get_public_ip()
    print(f" 公网IP地址: \033[1;32m{public_ip}\033[0m")

    print("\n 系统信息:")
    sys_info = get_system_info()
    print(f"  - 操作系统: {sys_info['system']['os']}")
    print(f"  - 最后启动: {sys_info['system']['boot_time']}")

    cpu = sys_info['cpu']
    print(f"\n CPU使用率: \033[1;33m{cpu['percent']}%\033[0m")
    print(f"  - 物理核心: {cpu['physical_cores']}核")
    print(f"  - 逻辑核心: {cpu['logical_cores']}核")

    mem = sys_info['memory']
    print(f"\n 内存使用: \033[1;33m{mem['percent']}%\033[0m")
    print(f"  - 总量: {mem['total']} GB")
    print(f"  - 已用: {mem['used']} GB")

    disk = sys_info['disk']
    print(f"磁盘使用: \033[1;33m{disk['percent']}%\033[0m")
    print(f"  - 总量: {disk['total']} GB")
    print(f"  - 已用: {disk['used']} GB")
