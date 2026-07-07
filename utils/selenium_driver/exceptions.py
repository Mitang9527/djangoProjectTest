# sync-init: skip
"""
异常体系
========

为 ``utils.selenium_driver`` 提供一套与 :mod:`utils.http_client` 风格一致的
异常类。所有异常都继承自 :class:`AutomationError`，业务代码可以一把抓。
"""
from __future__ import annotations


# ============================================================
# 基类
# ============================================================


class AutomationError(Exception):
    """所有 selenium_driver / appium 异常的基类。"""


# ============================================================
# 驱动 / Session
# ============================================================


class DriverError(AutomationError):
    """浏览器/驱动启动失败、版本不匹配、binary 找不到等。"""


class SessionError(DriverError):
    """Session 已失效（quit 后再操作、浏览器异常退出等）。"""


class ConfigError(AutomationError):
    """参数错误：browser 名称非法、capabilities 冲突等。"""


# ============================================================
# 元素 / 等待
# ============================================================


class ElementNotFoundError(AutomationError):
    """指定时间内未找到元素。"""


class WaitTimeoutError(ElementNotFoundError):
    """显式等待超时（ElementNotFoundError 的语义子集）。"""


class StaleElementError(AutomationError):
    """元素已从 DOM 摘除。"""


# ============================================================
# 截图 / 文件
# ============================================================


class ScreenshotError(AutomationError):
    """截图保存失败。"""


__all__ = [
    "AutomationError",
    "DriverError",
    "SessionError",
    "ConfigError",
    "ElementNotFoundError",
    "WaitTimeoutError",
    "StaleElementError",
    "ScreenshotError",
]
