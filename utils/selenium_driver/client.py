# sync-init: skip
"""
SeleniumClient 核心封装
========================

提供一组清爽的 API 覆盖日常 Web 自动化需求：

- 一行启动浏览器（自动 webdriver_manager 下载 driver）
- 显式等待（``wait().find()``）
- 链式操作（``input().click()``）
- 失败自动截图（``screenshot()`` / ``screenshot_on_fail()`` 装饰器）
- with 自动 quit
- 暴露 ``session`` / ``driver`` 两个别名给"我就想直接用 selenium"的人

参考 :mod:`utils.http_client` 的 API 风格。
"""
from __future__ import annotations

import functools
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.firefox.service import Service as FirefoxService
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.support.select import Select
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    from webdriver_manager.firefox import GeckoDriverManager
    _SELENIUM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SELENIUM_AVAILABLE = False

from loguru import logger

from .exceptions import (
    DriverError,
    SessionError,
    ScreenshotError,
    ConfigError,
)
from .locator import By, Waiter


# ============================================================
# 默认 default client（懒汉单例）
# ============================================================


_default_client: Optional["SeleniumClient"] = None


def get_default_client(**kwargs) -> "SeleniumClient":
    """获取/创建全局默认 client。"""
    global _default_client
    if _default_client is None or not _default_client.is_alive:
        _default_client = SeleniumClient(**kwargs)
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


class SeleniumClient:
    """Selenium Web 自动化客户端。

    Parameters
    ----------
    browser : str
        ``chrome`` / ``edge`` / ``firefox`` 之一。
    headless : bool
        是否无头模式。
    driver_path : str, optional
        自定义 webdriver 路径；不传则 webdriver_manager 自动下载。
    options : list[str]
        额外传给浏览器的命令行参数。
    download_dir : str, optional
        下载目录。
    window_size : (int, int)
        窗口大小；默认 ``(1280, 800)``。
    implicit_wait : float
        隐式等待秒数（兜底）；默认 0（推荐显式等待）。
    screenshot_dir : str
        失败截图保存目录；默认 ``logs/screenshots/``。
    page_load_timeout : float
        页面加载超时；默认 30s。
    """

    SUPPORTED_BROWSERS = ("chrome", "edge", "firefox")

    def __init__(
        self,
        *,
        browser: str = "chrome",
        headless: bool = False,
        driver_path: Optional[str] = None,
        options: Optional[list] = None,
        download_dir: Optional[str] = None,
        window_size: Tuple[int, int] = (1280, 800),
        implicit_wait: float = 0.0,
        screenshot_dir: str = "logs/screenshots",
        page_load_timeout: float = 30.0,
    ) -> None:
        if not _SELENIUM_AVAILABLE:
            raise DriverError(
                "selenium 未安装。请运行：\n"
                "  pip install selenium webdriver-manager"
            )
        if browser not in self.SUPPORTED_BROWSERS:
            raise ConfigError(
                f"browser={browser!r} not supported. "
                f"Choose from {self.SUPPORTED_BROWSERS}"
            )

        self.browser = browser
        self.headless = headless
        self.window_size = window_size
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._closed = False

        # 构建 webdriver
        self._driver = self._build_driver(
            browser=browser,
            headless=headless,
            driver_path=driver_path,
            options=options or [],
            download_dir=download_dir,
        )
        if implicit_wait:
            self._driver.implicitly_wait(implicit_wait)
        self._driver.set_page_load_timeout(page_load_timeout)
        self._driver.set_window_size(*window_size)
        logger.info(f"SeleniumClient started: browser={browser} headless={headless}")

    # ---- 内部构造 ----
    def _build_driver(self, *, browser, headless, driver_path, options, download_dir) -> "WebDriver":
        try:
            if browser == "chrome":
                opts = ChromeOptions()
                if headless:
                    opts.add_argument("--headless=new")
                if download_dir:
                    opts.add_experimental_option(
                        "prefs", {"download.default_directory": str(Path(download_dir).resolve())}
                    )
                for o in options:
                    opts.add_argument(o)
                path = driver_path or ChromeDriverManager().install()
                return webdriver.Chrome(service=ChromeService(path), options=opts)
            if browser == "edge":
                opts = EdgeOptions()
                if headless:
                    opts.add_argument("--headless=new")
                for o in options:
                    opts.add_argument(o)
                path = driver_path or EdgeChromiumDriverManager().install()
                return webdriver.Edge(service=EdgeService(path), options=opts)
            if browser == "firefox":
                opts = FirefoxOptions()
                if headless:
                    opts.add_argument("--headless")
                for o in options:
                    opts.add_argument(o)
                path = driver_path or GeckoDriverManager().install()
                return webdriver.Firefox(service=FirefoxService(path), options=opts)
        except Exception as e:
            raise DriverError(f"failed to start {browser}: {e}") from e
        raise ConfigError(f"unknown browser: {browser}")  # pragma: no cover

    # ---- 状态 ----
    @property
    def is_alive(self) -> bool:
        """session 是否还活着。"""
        if self._closed:
            return False
        try:
            # 拿一下 session_id 不抛错就说明活着
            _ = self._driver.session_id
            return True
        except Exception:
            return False

    @property
    def session(self) -> "WebDriver":
        """暴露底层 webdriver（给"我就想直接用 selenium"的人）。"""
        return self._driver

    @property
    def driver(self) -> "WebDriver":
        """session 的别名。"""
        return self._driver

    # ---- 导航 ----
    def get(self, url: str) -> "SeleniumClient":
        """打开 URL。"""
        self._check_alive()
        self._driver.get(url)
        return self

    def current_url(self) -> str:
        self._check_alive()
        return self._driver.current_url

    def title(self) -> str:
        self._check_alive()
        return self._driver.title

    def back(self) -> "SeleniumClient":
        self._check_alive()
        self._driver.back()
        return self

    def forward(self) -> "SeleniumClient":
        self._check_alive()
        self._driver.forward()
        return self

    def refresh(self) -> "SeleniumClient":
        self._check_alive()
        self._driver.refresh()
        return self

    # ---- 等待 ----
    def wait(self, timeout: Optional[float] = None, *, poll: Optional[float] = None) -> Waiter:
        """智能等待入口。

        Usage::

            web.wait().find(By.ID, "x")
            web.wait(5).find(By.CSS, ".y")
        """
        self._check_alive()
        return Waiter(self._driver)(timeout, poll=poll)

    # ---- 元素操作（直接走 driver） ----
    def find(self, by: str, value: str):
        """立即查找（不等待）。"""
        self._check_alive()
        return self._driver.find_element(by, value)

    def find_all(self, by: str, value: str) -> list:
        self._check_alive()
        return self._driver.find_elements(by, value)

    def input(self, by: str, value: str, text: str, *, clear: bool = True) -> "SeleniumClient":
        """找到输入框并填值。"""
        elem = self.wait().find(by, value)
        if clear:
            elem.clear()
        elem.send_keys(text)
        return self

    def click(self, by: str, value: str) -> "SeleniumClient":
        """找到元素并点击。"""
        self.wait().find(by, value).click()
        return self

    def text(self, by: str, value: str) -> str:
        return self.wait().find(by, value).text

    def attribute(self, by: str, value: str, name: str) -> Optional[str]:
        """取元素属性值。"""
        return self.wait().find(by, value).get_attribute(name)

    def is_displayed(self, by: str, value: str) -> bool:
        return self.wait().find(by, value).is_displayed()

    def submit(self, by: str, value: str) -> "SeleniumClient":
        """提交表单（按 Enter 等价物）。"""
        self.wait().find(by, value).submit()
        return self

    # ---- 鼠标高级操作（ActionChains） ----
    def right_click(self, by: str, value: str) -> "SeleniumClient":
        """右键单击元素（弹出 context menu / 自定义右键菜单）。"""
        elem = self.wait().find(by, value)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self._driver).context_click(elem).perform()
        return self

    def double_click(self, by: str, value: str) -> "SeleniumClient":
        """双击元素。"""
        elem = self.wait().find(by, value)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self._driver).double_click(elem).perform()
        return self

    def hover(self, by: str, value: str) -> "SeleniumClient":
        """鼠标悬停到元素（触发 hover 菜单 / tooltip）。"""
        elem = self.wait().find(by, value)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self._driver).move_to_element(elem).perform()
        return self

    def drag_to(
        self,
        source_by: str, source_value: str,
        target_by: str, target_value: str,
    ) -> "SeleniumClient":
        """把源元素拖到目标元素。"""
        src = self.wait().find(source_by, source_value)
        tgt = self.wait().find(target_by, target_value)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self._driver).drag_and_drop(src, tgt).perform()
        return self

    # ---- Alert 处理 ----
    def alert_text(self) -> str:
        """读取 alert 文本。"""
        self._check_alive()
        return self._driver.switch_to.alert.text

    def accept_alert(self) -> "SeleniumClient":
        """点击 alert 的"确定"。"""
        self._check_alive()
        self._driver.switch_to.alert.accept()
        return self

    def dismiss_alert(self) -> "SeleniumClient":
        """点击 alert 的"取消"。"""
        self._check_alive()
        self._driver.switch_to.alert.dismiss()
        return self

    # ---- Select 下拉框 ----
    def select(self, by: str, value: str) -> "_SelectHelper":
        """打开 <select> 下拉框。

        Usage::

            web.select(By.ID, "city").by_value("sh")
            web.select(By.ID, "city").by_text("上海")
            web.select(By.ID, "city").by_index(0)
        """
        if not _SELENIUM_AVAILABLE:
            raise DriverError("selenium 未安装")
        elem = self.wait().find(by, value)
        return _SelectHelper(self._driver, elem)

    # ---- 窗口 ----
    def maximize_window(self) -> "SeleniumClient":
        """最大化窗口（调试 / 截图时常用）。"""
        self._check_alive()
        self._driver.maximize_window()
        return self

    def open_new_window(self, trigger_by: str, trigger_value: str) -> "SeleniumClient":
        """点击元素触发新窗口，并自动切换到新窗口。

        用法::

            web.open_new_window(By.LINK_TEXT, "注册")
        """
        original = self._driver.current_window_handle
        self.click(trigger_by, trigger_value)
        # 等新窗口出现
        import time as _t
        for _ in range(20):  # 最多 10s
            if len(self._driver.window_handles) > 1:
                break
            _t.sleep(0.5)
        for h in self._driver.window_handles:
            if h != original:
                self._driver.switch_to.window(h)
                return self
        raise SessionError("open_new_window: 新窗口未出现")

    # ---- JS 执行 ----
    def execute_script(self, script: str, *args) -> Any:
        self._check_alive()
        return self._driver.execute_script(script, *args)

    def scroll_to_bottom(self) -> "SeleniumClient":
        self.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        return self

    def scroll_to(self, x: int, y: int) -> "SeleniumClient":
        self.execute_script(f"window.scrollTo({x}, {y});")
        return self

    # ---- iframe ----
    def frame(self, locator) -> "FrameContext":
        """切换到 iframe。

        Usage::

            with web.frame("iframe-name"):
                web.click(By.ID, "x")
        """
        self._check_alive()
        return FrameContext(self, locator)

    # ---- 窗口 ----
    def switch_to_window(self, index: int = -1) -> "SeleniumClient":
        handles = self._driver.window_handles
        self._driver.switch_to.window(handles[index])
        return self

    # ---- 截图 ----
    def screenshot(
        self,
        filename: Optional[str] = None,
        *,
        full_page: bool = False,
    ) -> str:
        """截图并返回文件路径。``filename`` 不传则按时间戳命名。"""
        self._check_alive()
        if not filename:
            filename = f"selenium_{int(time.time() * 1000)}.png"
        if not filename.endswith(".png"):
            filename += ".png"
        path = self.screenshot_dir / filename
        try:
            if full_page:
                # 通过 JS 取得完整高度再设窗口
                height = self.execute_script("return document.body.scrollHeight")
                self._driver.set_window_size(self.window_size[0], int(height))
                time.sleep(0.3)  # 等渲染
            self._driver.save_screenshot(str(path))
            logger.info(f"screenshot saved: {path}")
            return str(path)
        except Exception as e:
            raise ScreenshotError(f"failed to save screenshot: {e}") from e

    # ---- Cookie ----
    @property
    def cookies(self) -> "CookieHelper":
        return CookieHelper(self._driver)

    # ---- 关闭 ----
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._driver.quit()
            logger.info("SeleniumClient closed")
        except Exception as e:  # pragma: no cover
            logger.warning(f"SeleniumClient close error: {e}")

    def __enter__(self) -> "SeleniumClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- 内部 ----
    def _check_alive(self) -> None:
        if self._closed:
            raise SessionError("SeleniumClient 已关闭，请重新创建。")


# ============================================================
# iframe 上下文
# ============================================================


class FrameContext:
    """with 切换 iframe，离开时自动回到主文档。"""

    def __init__(self, client: SeleniumClient, locator) -> None:
        self._client = client
        self._locator = locator

    def __enter__(self):
        if isinstance(self._locator, (int, str)):
            self._client._driver.switch_to.frame(self._locator)
        else:
            # 传 (by, value) 走显式等待
            elem = self._client.wait().find(*self._locator)
            self._client._driver.switch_to.frame(elem)
        return self._client

    def __exit__(self, *exc):
        try:
            self._client._driver.switch_to.default_content()
        except Exception:  # pragma: no cover
            pass

# ============================================================
# Cookie helper
# ============================================================


class CookieHelper:
    def __init__(self, driver) -> None:
        self._driver = driver

    def get_all(self) -> list:
        return list(self._driver.get_cookies())

    def add(self, name: str, value: str, **kwargs) -> None:
        self._driver.add_cookie({"name": name, "value": value, **kwargs})

    def delete(self, name: str) -> None:
        self._driver.delete_cookie(name)

    def delete_all(self) -> None:
        self._driver.delete_all_cookies()

    def save(self, path: str) -> None:
        import json
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.get_all(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: str) -> None:
        import json
        cookies = json.loads(Path(path).read_text(encoding="utf-8"))
        for c in cookies:
            self._driver.add_cookie(c)


# ============================================================
# Select 辅助
# ============================================================


class _SelectHelper:
    """``<select>`` 下拉框的链式选择器。

    链式用法：

        web.select(By.ID, "city").by_value("sh")
        web.select(By.ID, "city").by_text("上海")
        web.select(By.ID, "city").by_index(0)
    """

    def __init__(self, driver, element) -> None:
        self._select = Select(element)

    def by_value(self, value: str) -> None:
        self._select.select_by_value(value)

    def by_text(self, text: str) -> None:
        self._select.select_by_visible_text(text)

    def by_index(self, index: int) -> None:
        self._select.select_by_index(index)

    def options(self) -> list:
        """返回所有 ``<option>`` 的 (value, text) 列表。"""
        return [(o.get_attribute("value"), o.text) for o in self._select.options]

    def first_selected(self) -> Optional[str]:
        """第一个被选中的 option 的 value。"""
        selected = self._select.first_selected_option
        return selected.get_attribute("value") if selected else None


# ============================================================
# 装饰器：失败自动截图
# ============================================================


def screenshot_on_fail(
    *,
    name: Optional[str] = None,
    full_page: bool = False,
    client_arg: str = "client",
) -> Callable:
    """装饰器：被装饰的函数抛异常时，自动从参数中找 SeleniumClient 截图。

    Usage::

        @screenshot_on_fail(name="login_step")
        def login(web: SeleniumClient):
            web.click(By.ID, "ghost")  # 失败自动存图
    """
    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                target = None
                # 优先从 kwargs 找
                target = kwargs.get(client_arg)
                # 再从 positional 找
                if target is None:
                    for a in args:
                        if isinstance(a, SeleniumClient):
                            target = a
                            break
                if isinstance(target, SeleniumClient) and target.is_alive:
                    try:
                        target.screenshot(name or func.__name__, full_page=full_page)
                    except Exception:  # pragma: no cover
                        logger.warning("screenshot_on_fail: screenshot failed")
                raise
        return wrapper
    return deco


__all__ = [
    "SeleniumClient",
    "FrameContext",
    "CookieHelper",
    "_SelectHelper",
    "screenshot_on_fail",
    "get_default_client",
    "close_default_client",
]
