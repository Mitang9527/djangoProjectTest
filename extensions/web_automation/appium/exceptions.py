# sync-init: skip
"""
AppiumClient 异常体系
=====================

与 :mod:`extensions.web_automation.selenium.exceptions` 共享同一套基类。
这里新增 3 个 appium 特有的异常。
"""
from __future__ import annotations

# 直接复用 selenium_driver 的异常，避免重复定义
from ..selenium.exceptions import (  # noqa: F401
    AutomationError,
    DriverError,
    SessionError,
    ConfigError,
    ElementNotFoundError,
    WaitTimeoutError,
    StaleElementError,
    ScreenshotError,
)


class AppNotInstalledError(AutomationError):
    """appPackage 指定的 app 未安装。"""


class DeviceNotFoundError(DriverError):
    """appium server 找不到 deviceName 指定的设备。"""


class ServerNotRunningError(DriverError):
    """appium server 没启动或连不上（默认 http://127.0.0.1:4723）。"""


__all__ = [
    "AutomationError",
    "DriverError",
    "SessionError",
    "ConfigError",
    "ElementNotFoundError",
    "WaitTimeoutError",
    "StaleElementError",
    "ScreenshotError",
    "AppNotInstalledError",
    "DeviceNotFoundError",
    "ServerNotRunningError",
]
