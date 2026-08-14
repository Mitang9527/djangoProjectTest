# sync-init: skip
"""
extensions.web_automation.playwright 聚合层
============================================

Re-export 所有公开符号。``__all__`` 与子模块 ``__all__`` 保持一致。
"""
from .client import (
    PlaywrightClient,
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
    BrowserNotInstalledError,
    ContextClosedError,
    CaptureError,
    ExportError,
)
from .api_capture import (
    APICaptureSession,
    CapturedAPI,
    CAPTURE_RESOURCE_TYPE_DEFAULT,
    IGNORE_KEYWORDS_DEFAULT,
    LOGIN_SELECTORS_DEFAULT,
)
from ..selenium.locator import By, Waiter  # 共享定位器命名空间

__all__ = [
    # client
    "PlaywrightClient",
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
    "BrowserNotInstalledError",
    "ContextClosedError",
    "CaptureError",
    "ExportError",
    # api_capture
    "APICaptureSession",
    "CapturedAPI",
    "CAPTURE_RESOURCE_TYPE_DEFAULT",
    "IGNORE_KEYWORDS_DEFAULT",
    "LOGIN_SELECTORS_DEFAULT",
    # locator (shared)
    "By",
    "Waiter",
]
