# sync-init: skip
"""
PlaywrightClient 核心封装
==========================

提供一组清爽的 API 覆盖日常 Web 自动化需求，与
:class:`extensions.web_automation.selenium.SeleniumClient`
和 :class:`extensions.web_automation.appium.AppiumClient` 保持一致的心智模型：

- 一行启动浏览器（chromium / chrome / msedge / firefox / webkit）
- 显式等待（``wait_for()``，默认使用 Playwright 原生 auto-waiting）
- 链式操作（``input().click()``）
- 失败自动截图（``screenshot()`` / ``screenshot_on_fail()`` 装饰器）
- with 自动 close
- 暴露 ``page`` / ``browser`` / ``context`` 三个别名给"我就想用原生 Playwright"的人
- 支持 API 抓包（见 :class:`extensions.web_automation.playwright.api_capture.APICaptureSession`）
"""
from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

try:
    import playwright as _pw_pkg  # noqa: F401 — 只用于 patching（import playwright.sync_api 模块级存在）
    import playwright.sync_api as _pw_sync_mod  # 模块级 patch 入口
except ImportError:  # pragma: no cover
    _pw_pkg = None  # type: ignore[assignment]
    _pw_sync_mod = None  # type: ignore[assignment]

try:
    from playwright.sync_api import (
        sync_playwright,
        Playwright as SyncPlaywright,
        Browser,
        BrowserContext,
        Page,
        Locator,
    )
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    SyncPlaywright = Any  # type: ignore[misc,assignment]
    Browser = BrowserContext = Page = Locator = Any  # type: ignore[misc,assignment]
    sync_playwright = None  # type: ignore[assignment]
    _PLAYWRIGHT_AVAILABLE = False

from loguru import logger

from .exceptions import (
    DriverError,
    SessionError,
    ScreenshotError,
    ConfigError,
    BrowserNotInstalledError,
    ContextClosedError,
)
from ..selenium.locator import By, Waiter  # 共享 By / Waiter 命名空间


# ============================================================
# 默认 default client（懒汉单例）
# ============================================================


_default_client: Optional["PlaywrightClient"] = None


def get_default_client(**kwargs) -> "PlaywrightClient":
    """获取/创建全局默认 client。"""
    global _default_client
    if _default_client is None or not _default_client.is_alive:
        _default_client = PlaywrightClient(**kwargs)
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
# 截图装饰器
# ============================================================


def screenshot_on_fail(func: Callable) -> Callable:
    """
    用在测试或爬取函数上，异常时自动截图。

    函数第一个参数必须是 PlaywrightClient（即 bound method 或显式传 client）。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        client: PlaywrightClient | None = None
        if args and isinstance(args[0], PlaywrightClient):
            client = args[0]
        elif "client" in kwargs and isinstance(kwargs["client"], PlaywrightClient):
            client = kwargs["client"]
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if client is not None and client.is_alive:
                try:
                    path = client.screenshot(f"fail_{func.__name__}")
                    logger.error(f"{func.__name__} 失败，截图已保存：{path}；原异常：{e}")
                except Exception as se:
                    logger.warning(f"{func.__name__} 失败，但额外截图也失败：{se}；原异常：{e}")
            raise

    return wrapper


# ============================================================
# 主类
# ============================================================


VALID_BROWSERS = {"chromium", "chrome", "msedge", "firefox", "webkit"}


class PlaywrightClient:
    """Playwright 浏览器自动化客户端。

    Parameters
    ----------
    browser : str
        ``chromium`` / ``chrome`` / ``msedge`` / ``firefox`` / ``webkit`` 之一。
    headless : bool
        是否无头模式。默认 ``False``（方便人工操作、抓包、调试）。
    channel : str, optional
        指定浏览器可执行渠道（如 ``chrome`` / ``msedge``）。不传则按 ``browser``
        自动匹配。
    options : list[str]
        额外传给浏览器的命令行参数，例如禁用代理、忽略证书等。
    download_dir : str, optional
        下载目录。
    viewport : (int, int)
        视口大小；默认 ``(1600, 900)``。
    ignore_https_errors : bool
        是否忽略 HTTPS 证书错误，默认 ``True``。
    screenshot_dir : str, optional
        截图保存目录；默认 ``logs/screenshots/``。
    user_data_dir : str, optional
        持久化用户数据目录（保存登录态）。
    extra_http_headers : dict[str, str], optional
        全局注入的 HTTP 请求头。
    trace_dir : str, optional
        Playwright Trace 记录目录，开启后每次 close() 会生成 .zip。
    default_timeout : int
        所有操作的默认超时毫秒数；默认 ``30_000``。
    default_navigation_timeout : int
        页面跳转的默认超时毫秒数；默认 ``60_000``。
    """

    # ---------------------------------------------------------
    # 生命周期
    # ---------------------------------------------------------

    def __init__(
        self,
        browser: str = "chromium",
        headless: bool = False,
        channel: Optional[str] = None,
        options: Optional[list[str]] = None,
        download_dir: Optional[str] = None,
        viewport: Tuple[int, int] = (1600, 900),
        ignore_https_errors: bool = True,
        screenshot_dir: Optional[str] = None,
        user_data_dir: Optional[str] = None,
        extra_http_headers: Optional[dict[str, str]] = None,
        trace_dir: Optional[str] = None,
        default_timeout: int = 30_000,
        default_navigation_timeout: int = 60_000,
    ):
        if not _PLAYWRIGHT_AVAILABLE:
            raise DriverError(
                "未安装 playwright，无法创建 PlaywrightClient。"
                "请执行：pip install playwright && playwright install chromium"
            )

        if browser not in VALID_BROWSERS:
            raise ConfigError(
                f"browser={browser!r} 非法，可选值为 {sorted(VALID_BROWSERS)}"
            )

        self._browser_name = browser
        self._headless = headless
        self._channel = channel
        self._options = list(options or [])
        self._download_dir = str(Path(download_dir).resolve()) if download_dir else None
        self._viewport = {"width": viewport[0], "height": viewport[1]}
        self._ignore_https_errors = ignore_https_errors
        self._user_data_dir = user_data_dir
        self._extra_http_headers = dict(extra_http_headers or {})
        self._trace_dir = trace_dir
        self._default_timeout = default_timeout
        self._default_navigation_timeout = default_navigation_timeout

        self.screenshot_dir = Path(screenshot_dir or "logs/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        # 生命周期内的实例（由 _launch() 填充）
        self._pw: SyncPlaywright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._closed: bool = False

        # 别名（让外部调 session/browser/page 都能用）
        self.driver: Page | None = None  # 与 SeleniumClient 对齐
        self.session: Page | None = None

        self._launch()

    # ---------------------------------------------------------
    # 内部：启动
    # ---------------------------------------------------------

    def _launch(self) -> None:
        try:
            self._pw = sync_playwright().start()
        except Exception as e:
            raise DriverError(f"启动 Playwright 运行时失败：{e}") from e

        # 根据 browser 选 BrowserType
        pw = self._pw
        if self._browser_name in ("chromium", "chrome", "msedge"):
            browser_type = pw.chromium
            resolved_channel = self._channel or (
                "chrome" if self._browser_name == "chrome"
                else "msedge" if self._browser_name == "msedge"
                else None
            )
        elif self._browser_name == "firefox":
            browser_type = pw.firefox
            resolved_channel = self._channel
        elif self._browser_name == "webkit":
            browser_type = pw.webkit
            resolved_channel = self._channel
        else:  # pragma: no cover
            raise ConfigError(f"未知 browser：{self._browser_name}")

        launch_kwargs: dict[str, Any] = {
            "headless": self._headless,
            "args": self._options,
        }
        if resolved_channel:
            launch_kwargs["channel"] = resolved_channel

        try:
            self._browser = browser_type.launch(**launch_kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "executable doesn't exist" in msg or "playwright install" in msg:
                raise BrowserNotInstalledError(
                    "Playwright 浏览器二进制不存在，请执行："
                    f"playwright install {self._browser_name}"
                ) from e
            raise DriverError(f"启动 {self._browser_name} 浏览器失败：{e}") from e

        # context 参数
        ctx_kwargs: dict[str, Any] = {
            "viewport": self._viewport,
            "ignore_https_errors": self._ignore_https_errors,
        }
        if self._user_data_dir:
            # 持久化上下文 => 需要用 launch_persistent_context
            # 为简化 API，这里用 browser.new_context 加 storage_state 路径等价
            # 传 user_data_dir 时走 launch_persistent_context 分支
            pass
        if self._download_dir:
            ctx_kwargs["accept_downloads"] = True
        if self._extra_http_headers:
            ctx_kwargs["extra_http_headers"] = self._extra_http_headers

        try:
            if self._user_data_dir:
                # 持久化上下文（复用登录态）
                Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
                # 注意：持久化上下文必须通过 browser_type.launch_persistent_context 创建
                # 所以关闭上面通过 launch() 打开的临时 browser，重新创建 persistent
                self._browser.close()
                self._browser = None
                ctx_kwargs.pop("viewport", None)  # 某些版本 persistent 要放到外层
                self._context = browser_type.launch_persistent_context(
                    user_data_dir=self._user_data_dir,
                    headless=self._headless,
                    channel=resolved_channel,
                    args=self._options,
                    viewport=self._viewport,
                    ignore_https_errors=self._ignore_https_errors,
                    accept_downloads=bool(self._download_dir),
                    extra_http_headers=self._extra_http_headers or None,
                )
            else:
                self._context = self._browser.new_context(**ctx_kwargs)
        except Exception as e:
            raise DriverError(f"创建 BrowserContext 失败：{e}") from e

        # 超时
        self._context.set_default_timeout(self._default_timeout)
        self._context.set_default_navigation_timeout(self._default_navigation_timeout)

        # 打开第一页
        try:
            self._page = self._context.new_page()
        except Exception as e:
            raise DriverError(f"创建首页面失败：{e}") from e

        # 别名对齐
        self.driver = self._page
        self.session = self._page

        # 开启 trace（可选）
        if self._trace_dir:
            Path(self._trace_dir).mkdir(parents=True, exist_ok=True)
            try:
                self._context.tracing.start(screenshots=True, snapshots=True, sources=True)
            except Exception:
                # trace 非核心能力，失败不影响主流程
                logger.warning("Playwright tracing 启动失败，已跳过")

        logger.info(
            f"[PlaywrightClient] {self._browser_name} 启动成功 "
            f"(headless={self._headless}, viewport={self._viewport})"
        )

    # ---------------------------------------------------------
    # 生命周期：关闭 / with
    # ---------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        """浏览器/页面是否仍可用。"""
        if self._closed or self._context is None or self._page is None:
            return False
        try:
            # 直接访问 page.url 作为心跳，page 关了会抛
            _ = self._page.url
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # 写 trace
        if self._trace_dir and self._context is not None:
            try:
                trace_path = str(
                    Path(self._trace_dir)
                    / f"trace_{time.strftime('%Y%m%d_%H%M%S')}.zip"
                )
                self._context.tracing.stop(path=trace_path)
                logger.info(f"[PlaywrightClient] Trace 已保存：{trace_path}")
            except Exception:
                pass

        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass

        self._page = self.driver = self.session = None
        self._context = None
        self._browser = None
        self._pw = None
        logger.info("[PlaywrightClient] 已关闭")

    def __enter__(self) -> "PlaywrightClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_alive(self) -> None:
        if not self.is_alive:
            raise ContextClosedError("PlaywrightClient 已关闭或浏览器已退出")

    # ---------------------------------------------------------
    # 原生句柄访问
    # ---------------------------------------------------------

    @property
    def page(self) -> Page:
        self._require_alive()
        assert self._page is not None
        return self._page

    @property
    def context(self) -> BrowserContext:
        self._require_alive()
        assert self._context is not None
        return self._context

    @property
    def browser(self) -> Browser:
        if self._closed or self._browser is None:
            raise ContextClosedError("PlaywrightClient 已关闭或浏览器未启动")
        assert self._browser is not None
        return self._browser

    # ---------------------------------------------------------
    # 常用高级 API（与 SeleniumClient/AppiumClient 对齐）
    # ---------------------------------------------------------

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self._require_alive()
        logger.debug(f"[PlaywrightClient] goto: {url}")
        self._page.goto(url, wait_until=wait_until)

    def wait_for_load_state(self, state: str = "networkidle", timeout_ms: int | None = None) -> None:
        self._require_alive()
        self._page.wait_for_load_state(state, timeout=timeout_ms)

    def wait_for_timeout(self, milliseconds: int) -> None:
        self._require_alive()
        self._page.wait_for_timeout(milliseconds)

    def _to_locator(self, by: str, value: str, first: bool = True) -> Locator:
        """把 By.xxx 策略映射到 Playwright 的定位方式。"""
        self._require_alive()
        assert self._page is not None
        if by == By.ID:
            loc = self._page.locator(f"#{value}")
        elif by == By.CSS_SELECTOR or by == By.CSS:
            loc = self._page.locator(value)
        elif by == By.XPATH:
            loc = self._page.locator(f"xpath={value}")
        elif by == By.NAME:
            loc = self._page.locator(f'[name="{value}"]')
        elif by == By.LINK_TEXT:
            loc = self._page.get_by_text(value, exact=True)
        elif by == By.PARTIAL_LINK_TEXT:
            loc = self._page.get_by_text(value)
        elif by == By.TAG_NAME:
            loc = self._page.locator(value)
        elif by == By.CLASS_NAME:
            loc = self._page.locator(f".{value}")
        elif by == By.PLACEHOLDER:
            loc = self._page.get_by_placeholder(value)
        elif by == By.LABEL:
            loc = self._page.get_by_label(value)
        elif by == By.TEST_ID:
            loc = self._page.get_by_test_id(value)
        else:
            # 兜底：按字符串透传为 css selector
            loc = self._page.locator(value)
        return loc.first if first else loc

    def _element(self, by: str, value: str) -> Locator:
        loc = self._to_locator(by, value, first=True)
        loc.wait_for(state="visible")
        return loc

    def wait(self, timeout_seconds: float = 10.0, poll_seconds: float = 0.2) -> Waiter:
        """
        返回与 selenium 共享的 Waiter 对象（用于复杂循环等待）。

        注意：简单场景建议直接用 Playwright 原生的 locator.wait_for()。
        """
        return Waiter(self, default_timeout=timeout_seconds, default_poll=poll_seconds)

    def click(self, by: str, value: str, timeout_ms: int | None = None) -> "PlaywrightClient":
        self._element(by, value).click(timeout=timeout_ms)
        return self

    def input(self, by: str, value: str, text: str, clear_first: bool = True) -> "PlaywrightClient":
        el = self._element(by, value)
        if clear_first:
            try:
                el.fill("")
            except Exception:
                # 部分 input 不支持 fill("")，用 click+全选+删除兜底
                el.click()
                self._page.keyboard.press("Control+a")
                self._page.keyboard.press("Delete")
        el.fill(text)
        return self

    def type_text(self, text: str, delay_ms: int = 0) -> "PlaywrightClient":
        self._require_alive()
        self._page.keyboard.type(text, delay=delay_ms)
        return self

    def press_key(self, key: str) -> "PlaywrightClient":
        self._require_alive()
        self._page.keyboard.press(key)
        return self

    def text(self, by: str, value: str) -> str:
        el = self._element(by, value)
        return el.inner_text() or el.input_value()

    def get_attribute(self, by: str, value: str, name: str) -> str | None:
        return self._element(by, value).get_attribute(name)

    def is_visible(self, by: str, value: str, timeout_ms: int = 0) -> bool:
        try:
            return self._to_locator(by, value, first=True).is_visible(timeout=timeout_ms)
        except Exception:
            return False

    def count(self, by: str, value: str) -> int:
        return self._to_locator(by, value, first=False).count()

    def select_option(
        self, by: str, value: str,
        label: Optional[str] = None,
        val: Optional[str] = None,
        index: Optional[int] = None,
    ) -> "PlaywrightClient":
        el = self._element(by, value)
        if label is not None:
            el.select_option(label=label)
        elif val is not None:
            el.select_option(value=val)
        elif index is not None:
            el.select_option(index=index)
        else:
            raise ConfigError("select_option 至少传 label / value / index 之一")
        return self

    def check(self, by: str, value: str, checked: bool = True) -> "PlaywrightClient":
        el = self._element(by, value)
        if checked:
            el.check()
        else:
            el.uncheck()
        return self

    # ---------------------------------------------------------
    # 浏览器 / 页面管理
    # ---------------------------------------------------------

    def new_page(self) -> Page:
        self._require_alive()
        self._page = self._context.new_page()
        self.driver = self.session = self._page
        return self._page

    def new_tab(self, url: Optional[str] = None) -> Page:
        """别名。Playwright 没有 tab 概念，等价 new_page 并可选择性 goto。"""
        page = self.new_page()
        if url:
            page.goto(url)
        return page

    def pages(self) -> list[Page]:
        self._require_alive()
        return list(self._context.pages)

    def switch_to_page(self, index: int = -1) -> Page:
        pages = self.pages()
        if not pages:
            raise SessionError("当前没有任何打开的页面")
        self._page = pages[index]
        self.driver = self.session = self._page
        return self._page

    @property
    def url(self) -> str:
        self._require_alive()
        assert self._page is not None
        return self._page.url

    @property
    def title(self) -> str:
        self._require_alive()
        assert self._page is not None
        return self._page.title()

    def back(self) -> "PlaywrightClient":
        self._require_alive()
        self._page.go_back()
        return self

    def forward(self) -> "PlaywrightClient":
        self._require_alive()
        self._page.go_forward()
        return self

    def reload(self, wait_until: str = "domcontentloaded") -> "PlaywrightClient":
        self._require_alive()
        self._page.reload(wait_until=wait_until)
        return self

    # ---------------------------------------------------------
    # 截图
    # ---------------------------------------------------------

    def screenshot(
        self,
        name: Optional[str] = None,
        full_page: bool = True,
    ) -> str:
        """截图并返回保存后的绝对路径。"""
        self._require_alive()
        assert self._page is not None

        fname = name or f"playwright_{time.strftime('%Y%m%d_%H%M%S')}"
        if not fname.lower().endswith(".png"):
            fname = f"{fname}.png"

        path = str(self.screenshot_dir / fname)

        try:
            self._page.screenshot(path=path, full_page=full_page)
            logger.debug(f"[PlaywrightClient] 截图：{path}")
            return str(Path(path).resolve())
        except Exception as e:
            raise ScreenshotError(f"Playwright 截图失败：{e}") from e

    # ---------------------------------------------------------
    # Cookie / 存储状态
    # ---------------------------------------------------------

    def get_cookies(self) -> list[dict]:
        self._require_alive()
        return list(self._context.cookies())

    def set_cookies(self, cookies: list[dict]) -> None:
        self._require_alive()
        self._context.add_cookies(cookies)

    def clear_cookies(self) -> None:
        self._require_alive()
        self._context.clear_cookies()

    def storage_state(self, path: Optional[str] = None) -> dict:
        """
        导出登录态 storage_state。
        - 不传 ``path``：直接返回字典
        - 传 ``path``：同时写入 JSON 文件，下次 new_context 时可载入
        """
        self._require_alive()
        state = self._context.storage_state(path=path)
        if path:
            logger.info(f"[PlaywrightClient] StorageState 已保存：{path}")
        return state

    # ---------------------------------------------------------
    # JS 执行
    # ---------------------------------------------------------

    def evaluate(self, script: str, *args) -> Any:
        self._require_alive()
        return self._page.evaluate(script, *args)


__all__ = [
    "PlaywrightClient",
    "screenshot_on_fail",
    "get_default_client",
    "close_default_client",
    "By",
    "Waiter",
]
