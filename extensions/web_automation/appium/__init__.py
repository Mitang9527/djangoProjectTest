# sync-init: skip
"""
framework.appium 聚合层
===================

Re-export 所有公开符号。
"""
from .client import (
    AppiumClient,
    By,
    get_default_client,
    close_default_client,
)
from .exceptions import (
    AutomationError,
    DriverError,
    SessionError,
    ConfigError,
    ElementNotFoundError,
    WaitTimeoutError,
    StaleElementError,
    ScreenshotError,
    AppNotInstalledError,
    DeviceNotFoundError,
    ServerNotRunningError,
)
# 复用 selenium_driver 的 Waiter（同一套等待协议）
from ..selenium.locator import Waiter  # noqa: F401

__all__ = [
    # client
    "AppiumClient",
    "By",
    "get_default_client",
    "close_default_client",
    # exceptions
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
    # locator (复用)
    "Waiter",
]
