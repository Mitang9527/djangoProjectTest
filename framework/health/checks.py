"""
健康检查检查器。

复用 service_banner 的启动检查函数（check_database / check_broker /
check_redis_from_cache），保证"启动检查"与"就绪检查"判断口径一致。
额外检查可通过 register_check 注册。
"""
from typing import Callable, List

from framework.log_utils.service_banner import (
    CheckResult,
    check_broker,
    check_database,
    check_redis_from_cache,
)

# 外部可注册的额外就绪检查
_EXTRA_CHECKS: List[Callable[[], CheckResult]] = []


def register_check(fn: Callable[[], CheckResult]) -> Callable[[], CheckResult]:
    """注册一个额外的就绪检查（返回 CheckResult）。"""
    _EXTRA_CHECKS.append(fn)
    return fn


def default_readiness_checks() -> List[Callable[[], CheckResult]]:
    """默认就绪检查集：DB / Cache(Redis) / Broker。"""
    return [check_database, check_redis_from_cache, check_broker]


def collect_readiness() -> List[CheckResult]:
    """执行全部就绪检查，返回结果列表（单个检查异常不抛出，记 FAIL）。"""
    results: List[CheckResult] = []
    for fn in default_readiness_checks() + list(_EXTRA_CHECKS):
        name = getattr(fn, "__name__", "check")
        try:
            results.append(fn())
        except Exception as exc:  # 检查器自身异常不应让探针 500
            results.append(CheckResult(name, False, f"检查器异常: {type(exc).__name__}: {exc}"))
    return results
