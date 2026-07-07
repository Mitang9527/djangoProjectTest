# sync-init: skip
"""
AppiumClient 核心封装
======================

为移动端自动化提供清爽的 API：

- 启动会话（自动根据 platform 选 Options）
- 显式等待（``wait().find()``）
- 链式操作（``input().click()``）
- 设备交互（``swipe`` / ``tap`` / ``back`` / ``home``）
- 失败自动截图
- with 自动 quit

设计：与 :class:`utils.selenium_driver.SeleniumClient` 对齐，
保持调用方跨 Web / Mobile 时心智一致。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional, Tuple

try:
    from appium import webdriver as appium_webdriver
    from appium.options.android import UiAutomator2Options
    from appium.options.ios import XCUITestOptions
    from appium.webdriver.common.appiumby import AppiumBy
    _APPIUM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _APPIUM_AVAILABLE = False

from loguru import logger

from utils.selenium_driver.locator import By as _SharedBy, Waiter
from utils.selenium_driver.exceptions import (
    DriverError,
    SessionError,
    ConfigError,
    ScreenshotError,
)
from .exceptions import AppNotInstalledError, ServerNotRunningError


# ============================================================
# By：把 AppiumBy 也揉进同一个 By 命名空间
# ============================================================


class By(_SharedBy):
    """扩展 :class:`utils.selenium_driver.By`，加上 appium 特有策略。"""
    # 这里已经继承了 selenium_driver 的 By 常量；appium 的策略
    # 直接用同一个字符串值即可（appium server 认同一套 key）
    pass


# ============================================================
# 默认 default client
# ============================================================


_default_client: Optional["AppiumClient"] = None


def get_default_client(**kwargs) -> "AppiumClient":
    """获取/创建全局默认 client。"""
    global _default_client
    if _default_client is None or not _default_client.is_alive:
        _default_client = AppiumClient(**kwargs)
    return _default_client


def close_default_client() -> None:
    """关闭全局默认 client。"""
    global _default_client
    if _default_client is not None:
        try:
            _default_client.close()
        finally:
            _default_client = None


# ============================================================
# 主类
# ============================================================


class AppiumClient:
    """Appium 移动端自动化客户端。

    Parameters
    ----------
    platform : str
        ``android`` / ``ios`` 之一。
    device_name : str
        设备名（如 ``emulator-5554`` / ``iPhone 15``）。
    remote_url : str
        appium server 地址；默认 ``http://127.0.0.1:4723``。
    app_package : str, optional
        Android app 包名。
    app_activity : str, optional
        Android 启动 Activity。
    bundle_id : str, optional
        iOS app bundle id。
    platform_version : str, optional
        系统版本。
    no_reset : bool
        是否保留上一次 session 的 app 数据。
    full_reset : bool
        是否卸载重装（与 ``no_reset`` 互斥）。
    screenshot_dir : str
        失败截图保存目录。
    implicit_wait : float
        隐式等待秒数；默认 0（推荐显式等待）。
    new_command_timeout : float
        appium server 端 new command timeout；默认 60s。
    extra_caps : dict
        直接透传给 options 的额外 capabilities。
    """

    SUPPORTED_PLATFORMS = ("android", "ios")

    def __init__(
        self,
        *,
        platform: str = "android",
        device_name: str,
        remote_url: str = "http://127.0.0.1:4723",
        app_package: Optional[str] = None,
        app_activity: Optional[str] = None,
        bundle_id: Optional[str] = None,
        platform_version: Optional[str] = None,
        no_reset: bool = True,
        full_reset: bool = False,
        screenshot_dir: str = "logs/screenshots",
        implicit_wait: float = 0.0,
        new_command_timeout: float = 60.0,
        extra_caps: Optional[dict] = None,
    ) -> None:
        if not _APPIUM_AVAILABLE:
            raise DriverError(
                "appium-python-client 未安装。请运行：\n"
                "  pip install appium-python-client"
            )
        if platform not in self.SUPPORTED_PLATFORMS:
            raise ConfigError(
                f"platform={platform!r} not supported. "
                f"Choose from {self.SUPPORTED_PLATFORMS}"
            )
        if no_reset and full_reset:
            raise ConfigError("no_reset 和 full_reset 不能同时为 True")

        self.platform = platform
        self.device_name = device_name
        self.remote_url = remote_url
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._closed = False

        # 构造 options
        options = self._build_options(
            platform=platform,
            device_name=device_name,
            app_package=app_package,
            app_activity=app_activity,
            bundle_id=bundle_id,
            platform_version=platform_version,
            no_reset=no_reset,
            full_reset=full_reset,
            new_command_timeout=new_command_timeout,
            extra_caps=extra_caps or {},
        )

        # 启动 session
        try:
            self._driver = appium_webdriver.Remote(remote_url, options=options)
        except Exception as e:
            msg = str(e).lower()
            if "connection refused" in msg or "maxretryerror" in msg:
                raise ServerNotRunningError(
                    f"appium server 连不上: {remote_url}\n"
                    f"请先启动: appium"
                ) from e
            if "device" in msg and "not found" in msg:
                raise ServerNotRunningError(
                    f"找不到 device {device_name!r}: {e}"
                ) from e
            raise DriverError(f"启动 appium session 失败: {e}") from e

        if implicit_wait:
            self._driver.implicitly_wait(implicit_wait)
        logger.info(
            f"AppiumClient started: platform={platform} device={device_name} remote={remote_url}"
        )

    # ---- 内部构造 ----
    def _build_options(self, **kw) -> Any:
        if kw["platform"] == "android":
            opts = UiAutomator2Options()
            opts.device_name = kw["device_name"]
            if kw.get("app_package"):
                opts.app_package = kw["app_package"]
            if kw.get("app_activity"):
                opts.app_activity = kw["app_activity"]
        else:  # ios
            opts = XCUITestOptions()
            opts.device_name = kw["device_name"]
            if kw.get("bundle_id"):
                opts.bundle_id = kw["bundle_id"]
        if kw.get("platform_version"):
            opts.platform_version = kw["platform_version"]
        opts.no_reset = kw["no_reset"]
        opts.dont_stop_app_on_reset = kw["no_reset"]
        opts.new_command_timeout = int(kw["new_command_timeout"])
        for k, v in (kw["extra_caps"] or {}).items():
            setattr(opts, k, v)
        return opts

    # ---- 状态 ----
    @property
    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            _ = self._driver.session_id
            return True
        except Exception:
            return False

    @property
    def session(self) -> Any:
        return self._driver

    @property
    def driver(self) -> Any:
        return self._driver

    # ---- 启动 app ----
    def launch_app(self) -> "AppiumClient":
        """通过 ``mobile: startActivity`` 启动 android app（iOS 用 launch_app）。"""
        self._check_alive()
        if self.platform == "android":
            self._driver.execute_script(
                "mobile: startActivity",
                {"intent": f"{self._options_for_intent()}"},
            )
        else:
            self._driver.execute_script("mobile: launchApp")
        return self

    def _options_for_intent(self) -> str:
        # 留个口子给子类；用 options 里的 app_package/app_activity
        # 这里从 driver 拿 capabilities
        caps = self._driver.capabilities
        pkg = caps.get("appPackage", "")
        act = caps.get("appActivity", "")
        return f"{pkg}/{act}"

    def terminate_app(self, app_id: Optional[str] = None) -> "AppiumClient":
        self._check_alive()
        if app_id is None:
            app_id = self._driver.capabilities.get("appPackage") or self._driver.capabilities.get("bundleId")
        if not app_id:
            raise ConfigError("terminate_app 需要 app_id 或在 capabilities 中设置 appPackage/bundleId")
        self._driver.terminate_app(app_id)
        return self

    def is_app_installed(self, app_id: str) -> bool:
        self._check_alive()
        return bool(self._driver.is_app_installed(app_id))

    def install_app(self, path: str) -> "AppiumClient":
        self._check_alive()
        self._driver.install_app(path)
        return self

    def remove_app(self, app_id: str) -> "AppiumClient":
        self._check_alive()
        self._driver.remove_app(app_id)
        return self

    # ---- 等待 ----
    def wait(self, timeout: Optional[float] = None, *, poll: Optional[float] = None) -> Waiter:
        self._check_alive()
        return Waiter(self._driver)(timeout, poll=poll)

    # ---- 元素操作 ----
    def find(self, by: str, value: str):
        self._check_alive()
        return self._driver.find_element(by, value)

    def find_all(self, by: str, value: str) -> list:
        self._check_alive()
        return self._driver.find_elements(by, value)

    def input(self, by: str, value: str, text: str, *, clear: bool = True) -> "AppiumClient":
        elem = self.wait().find(by, value)
        if clear:
            elem.clear()
        elem.send_keys(text)
        return self

    def click(self, by: str, value: str) -> "AppiumClient":
        self.wait().find(by, value).click()
        return self

    def text(self, by: str, value: str) -> str:
        return self.wait().find(by, value).text

    def long_click(
        self, by: str, value: str, *, duration_ms: int = 1000
    ) -> "AppiumClient":
        """长按元素 N 毫秒（移动端 long-press 语义）。

        用 Appium 的 W3C actions API，**先按下元素 → 暂停 N ms → 抬起**，
        是真正可靠的长按实现（老代码用 ``click_and_hold`` + sleep 早已失
        效：第二次 ``release().perform()`` 作用在当前鼠标位置而不是元素上）。

        Usage::

            app.long_click(By.ID, "speak-btn", duration_ms=2000)
        """
        from selenium.webdriver.common.action_chains import ActionChains
        elem = self.wait().find(by, value)
        ActionChains(self._driver).click_and_hold(elem).pause(duration_ms / 1000).release().perform()
        return self

    # ---- 设备交互 ----
    def tap(self, x: int, y: int) -> "AppiumClient":
        """点击坐标。"""
        self._check_alive()
        self._driver.tap([(x, y)])
        return self

    def swipe(self, direction: str, *, ratio: float = 0.8) -> "AppiumClient":
        """方向滑动：``up``/``down``/``left``/``right``。``ratio`` 是滑动距离占屏比。"""
        self._check_alive()
        size = self._driver.get_window_size()
        w, h = size["width"], size["height"]
        cx, cy = w // 2, h // 2
        offset_x, offset_y = int(w * ratio / 2), int(h * ratio / 2)
        mapping = {
            "up": (cx, cy + offset_y, cx, cy - offset_y),
            "down": (cx, cy - offset_y, cx, cy + offset_y),
            "left": (cx + offset_x, cy, cx - offset_x, cy),
            "right": (cx - offset_x, cy, cx + offset_x, cy),
        }
        if direction not in mapping:
            raise ConfigError(f"swipe direction={direction!r} not in (up,down,left,right)")
        x1, y1, x2, y2 = mapping[direction]
        self._driver.swipe(x1, y1, x2, y2, duration=500)
        return self

    def back(self) -> "AppiumClient":
        """Android 物理返回键。"""
        self._check_alive()
        if self.platform == "android":
            self._driver.press_keycode(4)  # KEYCODE_BACK
        else:
            # iOS 没有全局 back，按需自行实现
            logger.warning("back() 在 iOS 上无操作，建议自行实现")
        return self

    def home(self) -> "AppiumClient":
        """回桌面。"""
        self._check_alive()
        if self.platform == "android":
            self._driver.press_keycode(3)  # KEYCODE_HOME
        else:
            self._driver.execute_script("mobile: pressButton", {"name": "home"})
        return self

    def keyevent(self, code: int) -> "AppiumClient":
        """Android 任意 keyevent。"""
        self._check_alive()
        if self.platform != "android":
            raise ConfigError("keyevent() 仅支持 android")
        self._driver.press_keycode(code)
        return self

    # ---- 截图 ----
    def screenshot(self, filename: Optional[str] = None) -> str:
        self._check_alive()
        if not filename:
            filename = f"appium_{int(time.time() * 1000)}.png"
        if not filename.endswith(".png"):
            filename += ".png"
        path = self.screenshot_dir / filename
        try:
            self._driver.save_screenshot(str(path))
            logger.info(f"screenshot saved: {path}")
            return str(path)
        except Exception as e:
            raise ScreenshotError(f"failed to save screenshot: {e}") from e

    # ---- App 信息 ----
    def current_app(self) -> dict:
        self._check_alive()
        return {
            "package": self._driver.current_package,
            "activity": self._driver.current_activity,
        }

    def device_info(self) -> dict:
        self._check_alive()
        caps = self._driver.capabilities
        return {
            "platform": caps.get("platformName"),
            "version": caps.get("platformVersion"),
            "device": caps.get("deviceModel") or caps.get("deviceName"),
            "udid": caps.get("udid"),
        }

    # ---- 关闭 ----
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._driver.quit()
            logger.info("AppiumClient closed")
        except Exception as e:  # pragma: no cover
            logger.warning(f"AppiumClient close error: {e}")

    def __enter__(self) -> "AppiumClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- 内部 ----
    def _check_alive(self) -> None:
        if self._closed:
            raise SessionError("AppiumClient 已关闭，请重新创建。")


__all__ = [
    "AppiumClient",
    "By",
    "get_default_client",
    "close_default_client",
]
