# sync-init: skip
"""
PlaywrightClient 异常体系
==========================

与 :mod:`extensions.web_automation.selenium.exceptions` 共享同一套基类。
这里新增 Playwright 特有的异常。
"""
from __future__ import annotations

# 直接复用 selenium_driver 的异常，保持三套自动化的异常体系一致
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


class BrowserNotInstalledError(DriverError):
    """Playwright 浏览器二进制未安装（需执行 playwright install chromium）。"""


class ContextClosedError(SessionError):
    """BrowserContext 已关闭（浏览器被手动关、page.close() 后再操作等）。"""


class CaptureError(AutomationError):
    """API 抓包 / 网络拦截 / HAR 导出等相关失败。"""


class ExportError(AutomationError):
    """Markdown/Excel/Postman 等导出失败。"""


__all__ = [
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
]
