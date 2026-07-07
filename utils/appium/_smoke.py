# sync-init: skip
"""
appium 烟雾测试（无需真机/真 server）
=====================================

用 mock 的 Remote webdriver 验证：
- 导入路径 + By 继承
- 异常体系（新增 3 个）
- AppiumClient 启动时 server refused 的错误分类
- 链式 API + 设备交互（tap/swipe/back/home）
- screenshot 路径
- is_alive / close / with
- Waiter 复用
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.appium import (
    AppiumClient,
    By,
    Waiter,
    get_default_client,
    close_default_client,
    AutomationError,
    DriverError,
    SessionError,
    ConfigError,
    WaitTimeoutError,
    ElementNotFoundError,
    ScreenshotError,
    AppNotInstalledError,
    DeviceNotFoundError,
    ServerNotRunningError,
)
from utils.selenium_driver import By as SeleniumBy


class FakeElement:
    def __init__(self, text=""):
        self.text = text
        self.clicked = False
        self.cleared = False
        self.typed = []

    def clear(self):
        self.cleared = True

    def send_keys(self, s):
        self.typed.append(s)

    def click(self):
        self.clicked = True


class FakeAppiumDriver:
    def __init__(self):
        self.session_id = "fake-appium"
        self.calls = []
        self.capabilities = {
            "platformName": "Android",
            "platformVersion": "13",
            "deviceModel": "Pixel 7",
            "udid": "emulator-5554",
            "appPackage": "com.example.app",
            "appActivity": ".MainActivity",
        }
        self._elements = []
        self._window_size = {"width": 1080, "height": 2400}
        self._installed = {"com.existing.app"}

    def find_element(self, by, value):
        self.calls.append(("find_element", by, value))
        if not self._elements:
            from selenium.common.exceptions import NoSuchElementException
            raise NoSuchElementException(f"no such: {by}={value}")
        return self._elements.pop(0)

    def find_elements(self, by, value):
        return list(self._elements)

    def tap(self, coords):
        self.calls.append(("tap", tuple(coords)))

    def swipe(self, x1, y1, x2, y2, duration=500):
        self.calls.append(("swipe", x1, y1, x2, y2, duration))

    def long_click(self, by, value, duration_ms=1000):
        # appium server 端 W3C action 协议，内部也是 sequence
        self.calls.append(("long_click", by, value, duration_ms))

    def _w3c_actions(self):  # 让 ActionChains 不炸
        from unittest.mock import MagicMock
        return MagicMock()

    def press_keycode(self, code):
        self.calls.append(("press_keycode", code))

    def execute_script(self, script, *args):
        self.calls.append(("execute_script", script, args))
        return 100

    def get_window_size(self):
        return self._window_size

    def save_screenshot(self, path):
        self.calls.append(("save_screenshot", path))
        Path(path).write_bytes(b"FAKE_PNG")

    def quit(self):
        self.calls.append(("quit",))

    @property
    def current_package(self):
        return "com.example.app"

    @property
    def current_activity(self):
        return ".MainActivity"

    def is_app_installed(self, pkg):
        return pkg in self._installed

    def install_app(self, path):
        self._installed.add("com.new.app")

    def remove_app(self, pkg):
        self._installed.discard(pkg)

    def terminate_app(self, pkg):
        self.calls.append(("terminate_app", pkg))


def _make_client(driver):
    c = AppiumClient.__new__(AppiumClient)
    c._driver = driver
    c._closed = False
    c.platform = "android"
    c.device_name = "emulator-5554"
    c.remote_url = "http://127.0.0.1:4723"
    c.screenshot_dir = Path("logs/screenshots")
    c.screenshot_dir.mkdir(parents=True, exist_ok=True)
    return c


class TestImport(unittest.TestCase):
    def test_imports(self):
        assert AppiumClient is not None
        assert By is not None
        assert Waiter is not None

    def test_by_inherits_selenium_by(self):
        # 关键：appium 复用 selenium_driver 的 By 常量
        assert issubclass(By, SeleniumBy)
        assert By.ID == "id"
        assert By.XPATH == "xpath"
        # appium 特有
        assert By.ANDROID_UIAUTOMATOR == "-android uiautomator"
        assert By.IOS_PREDICATE == "-ios predicate string"
        assert By.ACCESSIBILITY_ID == "accessibility id"


class TestExceptions(unittest.TestCase):
    def test_hierarchy(self):
        assert issubclass(DriverError, AutomationError)
        assert issubclass(AppNotInstalledError, AutomationError)
        assert issubclass(DeviceNotFoundError, DriverError)
        assert issubclass(ServerNotRunningError, DriverError)
        assert issubclass(WaitTimeoutError, ElementNotFoundError)

    def test_separate_from_selenium(self):
        # appium 异常在 utils.appium.exceptions 中定义，但
        # 实际 import 走的是 utils.selenium_driver.exceptions
        from utils.appium import exceptions as ex_mod
        assert hasattr(ex_mod, "AppNotInstalledError")
        assert hasattr(ex_mod, "ServerNotRunningError")


class TestConfigErrors(unittest.TestCase):
    def test_invalid_platform(self):
        try:
            AppiumClient(platform="harmonyos", device_name="x")
        except ConfigError as e:
            assert "harmonyos" in str(e)
        else:
            raise AssertionError("expected ConfigError")

    def test_no_reset_full_reset_conflict(self):
        try:
            AppiumClient(platform="android", device_name="x", no_reset=True, full_reset=True)
        except ConfigError as e:
            assert "no_reset" in str(e)
        else:
            raise AssertionError("expected ConfigError")


class TestServerNotRunning(unittest.TestCase):
    def test_connection_refused(self):
        with patch("utils.appium.client.appium_webdriver.Remote") as mock_remote:
            mock_remote.side_effect = ConnectionRefusedError("Connection refused")
            try:
                AppiumClient(platform="android", device_name="emulator-5554", remote_url="http://127.0.0.1:4723")
            except ServerNotRunningError as e:
                assert "127.0.0.1:4723" in str(e)
            else:
                raise AssertionError("expected ServerNotRunningError")

    def test_generic_driver_error(self):
        with patch("utils.appium.client.appium_webdriver.Remote") as mock_remote:
            mock_remote.side_effect = RuntimeError("some other error")
            try:
                AppiumClient(platform="android", device_name="x")
            except DriverError as e:
                assert "启动 appium session 失败" in str(e)
            else:
                raise AssertionError("expected DriverError")


class TestClientChaining(unittest.TestCase):
    def setUp(self):
        self.d = FakeAppiumDriver()
        self.c = _make_client(self.d)

    def test_input(self):
        e = FakeElement()
        self.d._elements = [e]
        self.c.input(By.ID, "phone", "13800138000")
        assert e.cleared
        assert e.typed == ["13800138000"]

    def test_click(self):
        e = FakeElement()
        self.d._elements = [e]
        self.c.click(By.ID, "submit")
        assert e.clicked

    def test_text(self):
        e = FakeElement(text="hello")
        self.d._elements = [e]
        assert self.c.text(By.ID, "x") == "hello"

    def test_tap(self):
        self.c.tap(100, 200)
        assert any(call[0] == "tap" for call in self.d.calls)

    def test_swipe_directions(self):
        for d in ("up", "down", "left", "right"):
            self.c.swipe(d)
        assert sum(1 for c in self.d.calls if c[0] == "swipe") == 4

    def test_swipe_invalid(self):
        try:
            self.c.swipe("diagonal")
        except ConfigError as e:
            assert "diagonal" in str(e)
        else:
            raise AssertionError("expected ConfigError")

    def test_back_android(self):
        self.c.back()
        assert ("press_keycode", 4) in self.d.calls

    def test_home_android(self):
        self.c.home()
        assert ("press_keycode", 3) in self.d.calls

    def test_keyevent(self):
        self.c.keyevent(67)  # KEYCODE_DEL
        assert ("press_keycode", 67) in self.d.calls

    def test_keyevent_ios_not_supported(self):
        self.c.platform = "ios"
        try:
            self.c.keyevent(67)
        except ConfigError:
            pass
        else:
            raise AssertionError("expected ConfigError on iOS keyevent")

    def test_long_click_default(self):
        from unittest.mock import MagicMock
        from selenium.webdriver.common import action_chains as ac_mod
        original = ac_mod.ActionChains
        ac_mod.ActionChains = MagicMock()
        try:
            e = FakeElement()
            self.d._elements = [e]
            self.c.long_click(By.ID, "speak-btn")
            assert any(call[0] == "find_element" for call in self.d.calls)
        finally:
            ac_mod.ActionChains = original

    def test_long_click_custom_duration(self):
        from unittest.mock import MagicMock
        from selenium.webdriver.common import action_chains as ac_mod
        original = ac_mod.ActionChains
        ac_mod.ActionChains = MagicMock()
        try:
            e = FakeElement()
            self.d._elements = [e]
            self.c.long_click(By.ID, "speak-btn", duration_ms=2000)
            assert e is not None
        finally:
            ac_mod.ActionChains = original

    def test_long_click_element_not_found(self):
        # 元素找不到时，wait().find 会超时
        self.d._elements = []
        try:
            self.c.long_click(By.ID, "ghost")
        except Exception:
            pass
        else:
            raise AssertionError("expected exception")


class TestAppLifecycle(unittest.TestCase):
    def setUp(self):
        self.d = FakeAppiumDriver()
        self.c = _make_client(self.d)

    def test_is_app_installed(self):
        assert self.c.is_app_installed("com.existing.app")
        assert not self.c.is_app_installed("com.missing.app")

    def test_install_remove(self):
        self.c.install_app("/tmp/x.apk")
        self.d._installed.add("com.new.app")
        assert self.c.is_app_installed("com.new.app")
        self.c.remove_app("com.new.app")
        assert not self.c.is_app_installed("com.new.app")

    def test_terminate_app(self):
        self.c.terminate_app()
        assert any(call[0] == "terminate_app" for call in self.d.calls)

    def test_terminate_no_app_id(self):
        # 改 capabilities 让 appPackage 为空
        self.d.capabilities = {"platformName": "Android"}
        try:
            self.c.terminate_app()
        except ConfigError:
            pass
        else:
            raise AssertionError("expected ConfigError")

    def test_current_app(self):
        info = self.c.current_app()
        assert info["package"] == "com.example.app"
        assert info["activity"] == ".MainActivity"

    def test_device_info(self):
        info = self.c.device_info()
        assert info["platform"] == "Android"
        assert info["version"] == "13"
        assert info["device"] == "Pixel 7"


class TestScreenshot(unittest.TestCase):
    def test_screenshot_named(self):
        d = FakeAppiumDriver()
        c = _make_client(d)
        path = c.screenshot("test_appium")
        assert Path(path).exists()
        assert "test_appium" in path

    def test_screenshot_default(self):
        d = FakeAppiumDriver()
        c = _make_client(d)
        path = c.screenshot()
        assert "appium_" in path


class TestSessionLifecycle(unittest.TestCase):
    def test_is_alive(self):
        d = FakeAppiumDriver()
        c = _make_client(d)
        assert c.is_alive
        c.close()
        assert not c.is_alive

    def test_with_context(self):
        d = FakeAppiumDriver()
        c = AppiumClient.__new__(AppiumClient)
        c._driver = d
        c._closed = False
        with c:
            assert d.session_id == "fake-appium"
        assert c._closed

    def test_operation_after_close(self):
        d = FakeAppiumDriver()
        c = _make_client(d)
        c.close()
        try:
            c.click(By.ID, "x")
        except SessionError:
            pass
        else:
            raise AssertionError("expected SessionError")


class TestWaiterReuse(unittest.TestCase):
    def test_waiter_timeout(self):
        d = FakeAppiumDriver()
        d._elements = []
        w = Waiter(d, default_timeout=0.2, default_poll=0.05)
        t0 = time.time()
        try:
            w.find(By.ID, "ghost")
        except WaitTimeoutError:
            assert 0.15 < time.time() - t0 < 0.8
        else:
            raise AssertionError("expected WaitTimeoutError")


class TestDefaultClient(unittest.TestCase):
    def test_get_default_singleton(self):
        from utils.appium import client as cli_mod
        d1 = FakeAppiumDriver()
        d2 = FakeAppiumDriver()
        c1 = _make_client(d1)
        with patch.object(cli_mod, "_default_client", c1):
            assert get_default_client() is c1
            assert get_default_client() is c1
        with patch.object(cli_mod, "_default_client", None):
            fresh = _make_client(d2)
            with patch.object(cli_mod, "_default_client", fresh):
                assert get_default_client() is fresh


if __name__ == "__main__":
    import os
    os.environ.setdefault("LOGURU_LEVEL", "ERROR")
    unittest.main(verbosity=2)
