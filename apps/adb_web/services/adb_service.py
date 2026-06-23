"""基于 adbutils 库的 ADB 设备操作服务，从 adb_tools.py 剥离 Web 适用能力。"""

from __future__ import annotations

import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from loguru import logger

from adbutils import adb
from adbutils.errors import AdbError as LibAdbError

from ..exceptions import AdbDeviceNotFound, AdbOperationError


ENV_PRESETS = {
    "1": {"ip_address": "cndns.shanliptt.com:10200", "context": "show", "label": "国内2.0"},
    "2": {"ip_address": "sgdns.shanlipoc.com:10200", "context": "pocstar", "label": "海外环境"},
}

RECORDING_DIRS = ("/sdcard/Pictures/Screenshots", "/sdcard/DCIM/Screenshots")


class AdbService:
    """封装 adbutils，提供与 adb_tools.py 对应的 Web 端能力。"""

    def __init__(self, media_subdir: str = "adb"):
        self.media_root = Path(settings.MEDIA_ROOT) / media_subdir
        self.media_root.mkdir(parents=True, exist_ok=True)
        (self.media_root / "screenshots").mkdir(exist_ok=True)
        (self.media_root / "apks").mkdir(exist_ok=True)
        (self.media_root / "recordings").mkdir(exist_ok=True)
        (self.media_root / "logs").mkdir(exist_ok=True)

    def _resolve_device(self, serial: str):
        if not serial:
            raise AdbOperationError("请指定设备 serial")
        try:
            return adb.device(serial=serial)
        except LibAdbError as exc:
            raise AdbDeviceNotFound(f"设备 {serial} 不可用: {exc}") from exc

    def list_devices(self) -> list[dict[str, Any]]:
        devices = []
        for device in adb.device_list():
            try:
                devices.append(
                    {
                        "serial": device.serial,
                        "model": device.getprop("ro.product.model") or "",
                        "android_version": device.getprop("ro.build.version.release") or "",
                        "state": device.get_state(),
                    }
                )
            except LibAdbError as exc:
                logger.warning(f"读取设备 {device.serial} 信息失败: {exc}")
                devices.append({"serial": device.serial, "model": "", "android_version": "", "state": "unknown"})
        return devices

    def get_device_info(self, serial: str) -> dict[str, Any]:
        device = self._resolve_device(serial)
        return {
            "serial": device.serial,
            "model": device.getprop("ro.product.model") or "",
            "android_version": device.getprop("ro.build.version.release") or "",
            "state": device.get_state(),
            "brand": device.getprop("ro.product.brand") or "",
            "sdk_version": device.getprop("ro.build.version.sdk") or "",
        }

    def list_packages(self, serial: str, third_party: bool = True) -> list[str]:
        device = self._resolve_device(serial)
        try:
            if third_party:
                return sorted(device.list_packages(filter_list=["-3"]))
            return sorted(device.list_packages())
        except LibAdbError as exc:
            raise AdbOperationError(f"获取包名列表失败: {exc}") from exc

    def take_screenshot(self, serial: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_screenshot.png"
        filepath = self.media_root / "screenshots" / filename
        try:
            image = device.screenshot()
            image.save(filepath)
        except LibAdbError as exc:
            raise AdbOperationError(f"截图失败: {exc}") from exc
        media_url = f"{settings.MEDIA_URL}adb/screenshots/{filename}"
        return {"filename": filename, "path": str(filepath), "url": media_url}

    def run_shell(self, serial: str, command: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            output = device.shell(command)
        except LibAdbError as exc:
            raise AdbOperationError(f"Shell 命令执行失败: {exc}") from exc
        return {"command": command, "output": output}

    def clear_app_data(self, serial: str, package_name: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            output = device.shell(f"pm clear {package_name}")
        except LibAdbError as exc:
            raise AdbOperationError(f"清除应用数据失败: {exc}") from exc
        if "Success" not in output:
            raise AdbOperationError(f"清除应用数据失败: {output.strip() or '未知错误'}")
        return {"package_name": package_name, "message": f"已清除 {package_name} 的数据"}

    def stop_app(self, serial: str, package_name: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            device.app_stop(package_name)
        except LibAdbError as exc:
            raise AdbOperationError(f"结束应用进程失败: {exc}") from exc
        return {"package_name": package_name, "message": f"已结束 {package_name} 的进程"}

    def start_app(self, serial: str, package_name: str, activity: str | None = None) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            if activity:
                output = device.shell(f"am start -n {activity}")
            else:
                device.app_start(package_name)
                output = f"{package_name} 启动成功"
        except LibAdbError as exc:
            raise AdbOperationError(f"启动应用失败: {exc}") from exc
        if "Error" in output:
            raise AdbOperationError(f"启动应用失败: {output.strip()}")
        return {"package_name": package_name, "message": output.strip() or f"{package_name} 启动成功"}

    def uninstall_app(self, serial: str, package_name: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            output = device.shell(f"pm uninstall {package_name}")
        except LibAdbError as exc:
            raise AdbOperationError(f"卸载应用失败: {exc}") from exc
        if "Success" not in output:
            raise AdbOperationError(f"卸载失败: {output.strip()}")
        return {"package_name": package_name, "message": f"已将 {package_name} 成功卸载"}

    def install_apk(self, serial: str, apk_path: str | Path) -> dict[str, Any]:
        device = self._resolve_device(serial)
        apk_path = Path(apk_path)
        if not apk_path.exists():
            raise AdbOperationError(f"APK 文件不存在: {apk_path}")

        before = set(self.list_packages(serial))
        try:
            device.install(str(apk_path))
            result = "Success"
        except LibAdbError as exc:
            raise AdbOperationError(f"安装失败: {exc}") from exc

        after = set(self.list_packages(serial))
        new_packages = sorted(after - before)
        message = "安装成功"
        started = None
        if new_packages:
            started = new_packages[0]
            try:
                device.app_start(started)
                message = f"安装成功并已启动 {started}"
            except LibAdbError:
                message = f"安装成功，新包名: {started}（自动启动失败）"

        return {
            "result": result,
            "message": message,
            "new_package": started,
            "new_packages": new_packages,
        }

    def export_apk(self, serial: str, package_name: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        filename = f"{package_name}.apk"
        filepath = self.media_root / "apks" / filename
        try:
            info = device.app_info(package_name)
            if not info:
                raise AdbOperationError(f"找不到应用: {package_name}")
            device.sync.pull(info.path, str(filepath))
        except AdbOperationError:
            raise
        except LibAdbError as exc:
            raise AdbOperationError(f"导出 APK 失败: {exc}") from exc
        media_url = f"{settings.MEDIA_URL}adb/apks/{filename}"
        return {"package_name": package_name, "filename": filename, "url": media_url, "path": str(filepath)}

    def input_text(self, serial: str, text: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        switch_cmd = "ime set com.android.adbkeyboard/.AdbIME"
        try:
            switch_output = device.shell(switch_cmd)
            if "selected" not in switch_output:
                raise AdbOperationError("输入法切换失败，请确认已安装 AdbKeyboard")
            safe_text = text.replace("'", "\\'")
            device.shell(
                f"am broadcast -a ADB_INPUT_TEXT --es msg '{safe_text}'"
            )
        except AdbOperationError:
            raise
        except LibAdbError as exc:
            raise AdbOperationError(f"文本输入失败: {exc}") from exc
        return {"text": text, "message": "文本已发送"}

    def change_app_env(
        self,
        serial: str,
        account: str,
        password: str,
        env_preset: str | None = None,
        ip_address: str | None = None,
        context: str | None = None,
        restart_app: bool = True,
    ) -> dict[str, str]:
        if env_preset and env_preset in ENV_PRESETS:
            preset = ENV_PRESETS[env_preset]
            ip_address = preset["ip_address"]
            context = preset["context"]
        if not ip_address or not context:
            raise AdbOperationError("请提供环境 preset 或自定义 ip_address 与 context")

        device = self._resolve_device(serial)
        restart_flag = "true" if restart_app else "false"
        shell_cmd = (
            f"am broadcast -a com.echat.config "
            f"--es account {shlex.quote(account)} "
            f"--es pwd {shlex.quote(password)} "
            f"--es dns {shlex.quote(ip_address)} "
            f"--es context {shlex.quote(context)} "
            f"--ez restart_app {restart_flag}"
        )
        try:
            output = device.shell(shell_cmd)
        except LibAdbError as exc:
            raise AdbOperationError(f"环境参数写入失败: {exc}") from exc

        if "result=0" not in output:
            raise AdbOperationError(f"参数写入错误: {output.strip()}")
        return {
            "account": account,
            "dns": ip_address,
            "context": context,
            "message": f"已更改环境参数为 {ip_address}，版本为 {context}",
        }

    def open_language_settings(self, serial: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            output = device.shell("am start -a android.settings.LOCALE_SETTINGS")
        except LibAdbError as exc:
            raise AdbOperationError(f"打开语言设置失败: {exc}") from exc
        if "Error" in output:
            raise AdbOperationError(f"打开语言设置失败: {output.strip()}")
        return {"message": "已打开系统语言设置界面", "output": output.strip()}

    def clear_logcat(self, serial: str) -> dict[str, str]:
        device = self._resolve_device(serial)
        try:
            device.shell("logcat -c")
        except LibAdbError as exc:
            raise AdbOperationError(f"清理日志失败: {exc}") from exc
        return {"message": "日志已清理"}

    def dump_logcat(self, serial: str, keyword: str | None = None, lines: int = 500) -> dict[str, str]:
        device = self._resolve_device(serial)
        cmd = f"logcat -d -t {lines}"
        if keyword:
            cmd = f"logcat -d -t {lines} | grep -E {shlex.quote(keyword)}"
        try:
            output = device.shell(cmd)
        except LibAdbError as exc:
            raise AdbOperationError(f"读取日志失败: {exc}") from exc

        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_logcat.log"
        filepath = self.media_root / "logs" / filename
        filepath.write_text(output, encoding="utf-8", errors="replace")
        media_url = f"{settings.MEDIA_URL}adb/logs/{filename}"
        return {"filename": filename, "url": media_url, "lines": len(output.splitlines()), "preview": output[:2000]}

    def list_recordings(self, serial: str) -> dict[str, Any]:
        device = self._resolve_device(serial)
        active_dir = None
        files: list[str] = []

        for remote_dir in RECORDING_DIRS:
            try:
                output = device.shell(f"ls -rt {remote_dir}").strip()
            except LibAdbError:
                continue
            if output:
                active_dir = remote_dir
                files = [line for line in output.splitlines() if line.endswith(".mp4")]
                break

        indexed = [{"index": idx, "filename": name} for idx, name in enumerate(reversed(files))]
        return {"remote_dir": active_dir, "recordings": indexed}

    def pull_recording(self, serial: str, index: int) -> dict[str, str]:
        listing = self.list_recordings(serial)
        recordings = listing["recordings"]
        remote_dir = listing["remote_dir"]
        if not remote_dir or not recordings:
            raise AdbOperationError("设备上没有找到录屏文件")
        if index < 0 or index >= len(recordings):
            raise AdbOperationError(f"录屏序号无效，有效范围 0-{len(recordings) - 1}")

        filename = recordings[index]["filename"]
        device = self._resolve_device(serial)
        local_path = self.media_root / "recordings" / filename
        remote_path = f"{remote_dir}/{filename}"
        try:
            device.sync.pull(remote_path, str(local_path))
        except LibAdbError as exc:
            raise AdbOperationError(f"拉取录屏失败: {exc}") from exc

        media_url = f"{settings.MEDIA_URL}adb/recordings/{filename}"
        return {"filename": filename, "url": media_url, "remote_path": remote_path}

    def get_flow_stats(self, serial: str, package_name: str) -> dict[str, float]:
        device = self._resolve_device(serial)
        dumpsys = device.shell(f"dumpsys package {package_name}")
        user_id_match = re.search(r"userId=(\d+)", dumpsys)
        if not user_id_match:
            raise AdbOperationError("无法获取应用 userId")

        user_id = user_id_match.group(1)
        stats_output = device.shell("cat /proc/net/xt_qtaguid/stats")
        rmnet_up = rmnet_down = wifi_up = wifi_down = 0.0

        for line in stats_output.splitlines():
            if f"{user_id}]" not in line:
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            if "rmnet" in line and "0x0" in line:
                rmnet_up += int(parts[5]) / 1024
                rmnet_down += int(parts[7]) / 1024
            elif "wlan" in line and "0x0" in line:
                wifi_up += int(parts[5]) / 1024
                wifi_down += int(parts[7]) / 1024

        return {
            "package_name": package_name,
            "rmnet_up_kb": round(rmnet_up, 2),
            "rmnet_down_kb": round(rmnet_down, 2),
            "wifi_up_kb": round(wifi_up, 2),
            "wifi_down_kb": round(wifi_down, 2),
        }

    def run_monkey(
        self,
        serial: str,
        package_name: str,
        throttle: int = 500,
        seed: int = 1000,
        event_count: int = 1000,
    ) -> dict[str, str]:
        device = self._resolve_device(serial)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_monkey.log"
        filepath = self.media_root / "logs" / filename

        monkey_cmd = (
            f"monkey -p {package_name} --throttle {throttle} -v -v -v "
            f"--ignore-crashes --ignore-timeouts --ignore-security-exceptions "
            f"--ignore-native-crashes --monitor-native-crashes -s {seed} {event_count}"
        )
        try:
            output = device.shell(monkey_cmd, timeout=600)
        except LibAdbError as exc:
            raise AdbOperationError(f"Monkey 执行失败: {exc}") from exc

        filepath.write_text(output, encoding="utf-8", errors="replace")
        media_url = f"{settings.MEDIA_URL}adb/logs/{filename}"
        return {"filename": filename, "url": media_url, "message": "Monkey 执行结束", "preview": output[:2000]}

    def save_uploaded_apk(self, uploaded_file) -> Path:
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uploaded_file.name
        filepath = self.media_root / "apks" / filename
        with filepath.open("wb") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)
        return filepath

    @staticmethod
    def list_env_presets() -> list[dict[str, str]]:
        return [{"key": key, **value} for key, value in ENV_PRESETS.items()]
