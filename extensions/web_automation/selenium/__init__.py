# sync-init: skip
"""
extensions.web_automation.selenium 聚合层
=============================

Re-export 所有公开符号。``__all__`` 与子模块 ``__all__`` 保持一致。
"""
from .client import (
    SeleniumClient,
    FrameContext,
    CookieHelper,
    screenshot_on_fail,
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
)
from .locator import By, Waiter

__all__ = [
    # client
    "SeleniumClient",
    "FrameContext",
    "CookieHelper",
    "screenshot_on_fail",
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
    # locator
    "By",
    "Waiter",
]
