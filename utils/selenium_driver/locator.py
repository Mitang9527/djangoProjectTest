# sync-init: skip
"""
智能等待 + 多种定位策略
========================

把 ``selenium.webdriver.support.ui.WebDriverWait`` 收成一个清爽的
``SeleniumLocator`` / ``AppiumLocator`` 协议对象，让调用方写起来更顺：

    app.wait().find(By.ID, "login_btn").click()
    web.wait(10).find(By.CSS, ".btn").click()

支持秒级超时、轮询间隔、错误信息定制。
"""
from __future__ import annotations

import time
from typing import Any, Optional, Tuple

from .exceptions import WaitTimeoutError


# ============================================================
# By 策略
# ============================================================


class By:
    """定位策略常量（与 selenium.appium 兼容）。

    为了让 utils.appium / utils.selenium_driver 调用方用同一种
    ``By.ID`` / ``By.XPATH`` 写法，我们在这里做一层薄薄的常量映射。
    实际用 selenium 时直接 ``By.ID`` 等会指向 selenium 的 By；
    用 appium 时通过 ``get_by()`` 工厂取 appium 的 By。
    """

    ID = "id"
    XPATH = "xpath"
    CSS = "css selector"
    NAME = "name"
    CLASS_NAME = "class name"
    TAG_NAME = "tag name"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"
    ANDROID_UIAUTOMATOR = "-android uiautomator"
    IOS_PREDICATE = "-ios predicate string"
    IOS_CLASS_CHAIN = "-ios class chain"
    ACCESSIBILITY_ID = "accessibility id"


# ============================================================
# Waiter
# ============================================================


class Waiter:
    """智能等待器。

    Usage::

        web.wait().find(By.ID, "login_btn")        # 默认 10s
        web.wait(5).find(By.CSS, ".x")             # 自定义超时
        web.wait(5, poll=0.2).find(...)            # 显式轮询间隔
    """

    DEFAULT_TIMEOUT = 10.0
    DEFAULT_POLL = 0.5

    def __init__(
        self,
        driver: Any,
        *,
        default_timeout: float = DEFAULT_TIMEOUT,
        default_poll: float = DEFAULT_POLL,
    ) -> None:
        self._driver = driver
        self._default_timeout = default_timeout
        self._default_poll = default_poll

    # ---- 入口 ----
    def __call__(self, timeout: Optional[float] = None, *, poll: Optional[float] = None) -> "Waiter":
        """返回一个新的 Waiter（带覆盖的 timeout/poll），便于链式。"""
        return Waiter(
            self._driver,
            default_timeout=timeout if timeout is not None else self._default_timeout,
            default_poll=poll if poll is not None else self._default_poll,
        )

    # ---- 找单个元素 ----
    def find(self, by: str, value: str, *, timeout: Optional[float] = None) -> Any:
        """等待并返回第一个匹配元素；超时抛 :class:`WaitTimeoutError`。"""
        timeout = timeout if timeout is not None else self._default_timeout
        end = time.monotonic() + timeout
        last_exc: Optional[Exception] = None
        while time.monotonic() < end:
            try:
                elem = self._driver.find_element(by, value)
                if elem:
                    return elem
            except Exception as e:  # NoSuchElement / StaleElementReference
                last_exc = e
            time.sleep(self._default_poll)
        raise WaitTimeoutError(
            f"find({by}={value!r}) timeout after {timeout}s"
            + (f" (last: {type(last_exc).__name__}: {last_exc})" if last_exc else "")
        )

    # ---- 找所有元素 ----
    def find_all(self, by: str, value: str, *, timeout: Optional[float] = None) -> list:
        """等待直到至少有 1 个匹配，返回 list。"""
        timeout = timeout if timeout is not None else self._default_timeout
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            elems = self._driver.find_elements(by, value)
            if elems:
                return elems
            time.sleep(self._default_poll)
        return []

    # ---- 通用：直到某条件成立 ----
    def until(self, condition, *, timeout: Optional[float] = None, message: str = ""):
        """``condition(driver) -> truthy``，truthy 时返回；超时抛 WaitTimeoutError。

        ``condition`` 可传一个 lambda 或带 __call__ 的对象（兼容 selenium 的 EC）。
        """
        timeout = timeout if timeout is not None else self._default_timeout
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                result = condition(self._driver)
                if result:
                    return result
            except Exception as e:
                last_exc = e
            time.sleep(self._default_poll)
        raise WaitTimeoutError(
            message or f"condition {getattr(condition, '__name__', condition)!r} timeout after {timeout}s"
        )


__all__ = ["By", "Waiter"]
