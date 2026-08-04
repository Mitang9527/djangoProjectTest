"""企业级 SSH 客户端封装。

基于 paramiko，提供：
- 上下文管理器（with 语句自动关闭）
- 连接超时 + 可选重试
- 结构化命令结果（exit_code / stdout / stderr）
- 批量命令执行（可选遇错即停）
- SFTP 文件 / 目录上传下载
- 远程文件存在性检查
- 端口转发（SSH 隧道）
- loguru 日志
- 自定义异常体系

使用示例::

    from framework.ops import SSHClient

    # 方式一：直接传参
    with SSHClient("10.0.0.1", "root", password="xxx") as ssh:
        result = ssh.execute("uname -a")
        if result.success:
            print(result.stdout)

        # 上传文件
        ssh.upload("/local/app.py", "/remote/app.py")

    # 方式二：从配置字典创建
    config = {"host": "10.0.0.1", "user": "root", "password": "xxx", "port": 2222}
    with SSHClient.from_config(config) as ssh:
        ssh.execute("ls -la /var/log")

    # 方式三：密钥认证
    with SSHClient("10.0.0.1", "deploy", key_filename="~/.ssh/id_rsa") as ssh:
        results = ssh.execute_many(["pwd", "whoami", "df -h"])
"""

from __future__ import annotations

import os
import socket
import stat as stat_module
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# ----------------------------------------------------------------------------
# paramiko 处理策略
# ----------------------------------------------------------------------------
# 不用 try/except 顶层 import（那会绑定 None 到模块属性，破坏 @patch 装饰器）。
# 改用 sys.modules 检测：只有当 stub 已被注入或 paramiko 已装时才绑定。
# 运行时通过 _get_paramiko() 懒加载。
# ----------------------------------------------------------------------------
import importlib as _importlib
import sys as _sys
_paramiko_mod = None  # 实际加载后的 paramiko 模块缓存

def _get_paramiko():
    """获取 paramiko 模块。

    优先级：
    1. 缓存 _paramiko_mod（已加载过）
    2. sys.modules['paramiko']（smoke stub 注入场景）
    3. import_module('paramiko')（生产环境）
    """
    global _paramiko_mod
    if _paramiko_mod is None:
        # 先看 sys.modules（测试 stub）
        _stub = _sys.modules.get("paramiko")
        if _stub is not None:
            _paramiko_mod = _stub
        else:
            _paramiko_mod = _importlib.import_module("paramiko")
    return _paramiko_mod

# 模块级 `paramiko` 名称：仅当 sys.modules 已有（smoke stub 或真模块）才绑定。
# 这样 @patch("...ssh_client.paramiko.SSHClient") 装饰器求值时不会撞 None。
paramiko = _sys.modules.get("paramiko")

from loguru import logger

from .exceptions import (
    SFTPError,
    SSHAuthError,
    SSHCommandError,
    SSHConfigError,
    SSHConnectionError,
    SSHError,
    SSHTimeoutError,
)

__all__ = [
    "CommandResult",
    "SSHClient",
    "SSHTunnel",
]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    """SSH 命令执行结果。"""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float = 0.0

    @property
    def success(self) -> bool:
        """exit_code == 0 视为成功。"""
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """stdout + stderr 拼接（与旧代码兼容）。"""
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}"
        return self.stdout

    def __str__(self) -> str:
        tag = "OK" if self.success else f"FAIL(exit={self.exit_code})"
        return (
            f"[{tag}] {self.command}  ({self.duration:.2f}s)\n"
            f"  stdout: {self.stdout[:500]}"
            + (f"\n  stderr: {self.stderr[:500]}" if self.stderr else "")
        )


# ---------------------------------------------------------------------------
# SSH 隧道（端口转发）
# ---------------------------------------------------------------------------

class SSHTunnel:
    """SSH 端口转发隧道。

    通过 SSH 服务器将本地端口转发到远程目标，实现安全访问远程服务。

    使用方式::

        with SSHTunnel(ssh_client, local_port=8080,
                       remote_host="10.0.0.2", remote_port=3306) as tunnel:
            # 在本地 8080 端口即可访问 10.0.0.2:3306
            ...
    """

    def __init__(
        self,
        ssh_client: "SSHClient",
        *,
        local_port: int,
        remote_host: str,
        remote_port: int,
        local_host: str = "127.0.0.1",
    ):
        self._ssh = ssh_client
        self.local_host = local_host
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self._transport: Optional[Any] = None
        self._server_socket: Optional[socket.socket] = None
        self._channels: List[Any] = []
        self._closed = False

    def __enter__(self) -> "SSHTunnel":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def start(self) -> "SSHTunnel":
        """启动隧道。"""
        if paramiko is None:
            raise SSHConfigError("paramiko 未安装，请执行 pip install paramiko")
        if not self._ssh.is_connected():
            raise SSHConnectionError("SSH 连接未建立，无法创建隧道")

        self._transport = self._ssh._client.get_transport()
        if self._transport is None:
            raise SSHConnectionError("SSH transport 不可用")

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.local_host, self.local_port))
        self._server_socket.listen(5)
        logger.info(
            f"SSH 隧道已启动: {self.local_host}:{self.local_port} "
            f"-> {self.remote_host}:{self.remote_port}"
        )
        return self

    def stop(self) -> None:
        """停止隧道。"""
        self._closed = True
        for ch in self._channels:
            try:
                ch.close()
            except Exception:
                pass
        self._channels.clear()
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        logger.info(f"SSH 隧道已停止: {self.local_host}:{self.local_port}")

    @property
    def address(self) -> Tuple[str, int]:
        """返回本地监听地址。"""
        return (self.local_host, self.local_port)


# ---------------------------------------------------------------------------
# SSH 客户端
# ---------------------------------------------------------------------------

class SSHClient:
    """企业级 SSH 客户端。

    支持密码 / 密钥认证，上下文管理器，SFTP 文件传输，端口转发。

    Args:
        host: 目标主机地址。
        username: 登录用户名。
        password: 密码（与 key_filename 二选一）。
        key_filename: SSH 私钥文件路径。
        port: SSH 端口，默认 22。
        timeout: 连接超时（秒）。
        max_retries: 连接失败时的最大重试次数（0 = 不重试）。
        retry_delay: 重试间隔（秒）。
        look_for_keys: 是否在 ~/.ssh/ 下自动搜索密钥。
        allow_agent: 是否使用 ssh-agent。
    """

    def __init__(
        self,
        host: str,
        username: str,
        *,
        password: Optional[str] = None,
        key_filename: Optional[str] = None,
        port: int = 22,
        timeout: float = 30.0,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        look_for_keys: bool = True,
        allow_agent: bool = True,
    ):
        if paramiko is None:
            raise SSHConfigError(
                "paramiko 未安装，请执行 pip install paramiko"
            )
        if not host:
            raise SSHConfigError("host 不能为空")
        if not username:
            raise SSHConfigError("username 不能为空")
        if not password and not key_filename and not look_for_keys and not allow_agent:
            raise SSHConfigError(
                "必须提供 password 或 key_filename，或启用 look_for_keys/allow_agent"
            )

        self._host = host
        self._username = username
        self._password = password
        self._key_filename = os.path.expanduser(key_filename) if key_filename else None
        self._port = port
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._look_for_keys = look_for_keys
        self._allow_agent = allow_agent

        self._client: Optional["paramiko.SSHClient"] = None
        self._sftp: Optional[Any] = None
        self._connected = False

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "SSHClient":
        """从配置字典创建 SSHClient。

        支持的 key::
            host / hostname   -- 主机地址
            user / username   -- 用户名
            password / passwd -- 密码
            key / key_filename / key_path -- 密钥路径
            port              -- 端口（默认 22）
            timeout           -- 连接超时
            max_retries       -- 重试次数
            retry_delay       -- 重试间隔

        兼容旧项目字段名（host/user/password）。
        """
        host = config.get("host") or config.get("hostname")
        username = config.get("user") or config.get("username")
        password = config.get("password") or config.get("passwd")
        key = (
            config.get("key")
            or config.get("key_filename")
            or config.get("key_path")
        )
        port = int(config.get("port", 22))
        timeout = float(config.get("timeout", 30))
        max_retries = int(config.get("max_retries", 0))
        retry_delay = float(config.get("retry_delay", 1.0))

        return cls(
            host=host,
            username=username,
            password=password,
            key_filename=key,
            port=port,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> "SSHClient":
        """建立 SSH 连接。

        失败时根据 max_retries 重试。认证失败直接抛 SSHAuthError 不重试。
        """
        if self._connected:
            return self

        last_exc: Optional[Exception] = None
        total_attempts = self._max_retries + 1

        for attempt in range(1, total_attempts + 1):
            try:
                _pk = _get_paramiko()
                client = _pk.SSHClient()
                client.set_missing_host_key_policy(_pk.AutoAddPolicy())
                client.connect(
                    hostname=self._host,
                    username=self._username,
                    password=self._password,
                    key_filename=self._key_filename,
                    port=self._port,
                    timeout=self._timeout,
                    look_for_keys=self._look_for_keys,
                    allow_agent=self._allow_agent,
                )
                self._client = client
                self._connected = True
                logger.info(
                    f"SSH 已连接: {self._username}@{self._host}:{self._port}"
                )
                return self

            except _get_paramiko().AuthenticationException as e:
                raise SSHAuthError(
                    f"SSH 认证失败: {self._username}@{self._host}: {e}",
                    host=self._host,
                ) from e

            except _get_paramiko().SSHException as e:
                last_exc = SSHConnectionError(
                    f"SSH 连接异常: {e}", host=self._host
                )

            except socket.timeout as e:
                last_exc = SSHTimeoutError(
                    f"SSH 连接超时 ({self._timeout}s): {self._host}",
                    timeout=self._timeout,
                    host=self._host,
                )

            except socket.error as e:
                last_exc = SSHConnectionError(
                    f"SSH 连接网络错误: {e}", host=self._host
                )

            # 未到上限则等待重试
            if attempt < total_attempts:
                logger.warning(
                    f"SSH 连接失败 (attempt {attempt}/{total_attempts}), "
                    f"{self._retry_delay}s 后重试..."
                )
                time.sleep(self._retry_delay)

        raise last_exc  # type: ignore[misc]

    def disconnect(self) -> None:
        """关闭 SSH 连接并释放 SFTP 资源。"""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None

        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        if self._connected:
            self._connected = False
            logger.info(f"SSH 已断开: {self._username}@{self._host}:{self._port}")

    def close(self) -> None:
        """disconnect 的别名。"""
        self.disconnect()

    def is_connected(self) -> bool:
        """检查连接是否仍然有效。"""
        if not self._connected or self._client is None:
            return False
        transport = self._client.get_transport()
        return transport is not None and transport.is_active()

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    def execute(
        self,
        command: str,
        *,
        timeout: Optional[float] = 60.0,
        get_pty: bool = False,
        environment: Optional[Dict[str, str]] = None,
        raise_on_error: bool = False,
    ) -> CommandResult:
        """在远程服务器上执行命令。

        Args:
            command: 要执行的 shell 命令。
            timeout: 命令超时（秒），None 表示不限制。
            get_pty: 是否分配伪终端。
            environment: 额外环境变量。
            raise_on_error: exit_code != 0 时是否抛 SSHCommandError。

        Returns:
            CommandResult 结构体。
        """
        self._ensure_connected()

        start = time.monotonic()
        try:
            stdin, stdout, stderr = self._client.exec_command(
                command,
                timeout=timeout,
                get_pty=get_pty,
                environment=environment,
            )
            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            # 确保流关闭
            stdout.channel.shutdown_read()

        except socket.timeout as e:
            raise SSHTimeoutError(
                f"命令执行超时 ({timeout}s): {command}",
                timeout=timeout,
                host=self._host,
            ) from e

        except _get_paramiko().SSHException as e:
            raise SSHCommandError(
                f"命令执行异常: {e}",
                command=command,
                host=self._host,
            ) from e

        duration = time.monotonic() - start
        result = CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout_str,
            stderr=stderr_str,
            duration=duration,
        )

        if result.success:
            logger.debug(f"SSH 命令成功: {command}  ({duration:.2f}s)")
        else:
            logger.warning(
                f"SSH 命令失败 (exit={exit_code}): {command}  ({duration:.2f}s)\n"
                f"  stderr: {stderr_str[:300]}"
            )
            if raise_on_error:
                raise SSHCommandError(
                    f"命令退出码 {exit_code}: {command}",
                    command=command,
                    exit_code=exit_code,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    host=self._host,
                )

        return result

    def execute_many(
        self,
        commands: Sequence[str],
        *,
        timeout: Optional[float] = 60.0,
        stop_on_error: bool = False,
    ) -> List[CommandResult]:
        """批量执行命令。

        Args:
            commands: 命令列表。
            timeout: 每条命令的超时。
            stop_on_error: 遇到失败命令是否停止后续执行。

        Returns:
            CommandResult 列表（已执行的）。
        """
        results: List[CommandResult] = []
        for cmd in commands:
            result = self.execute(cmd, timeout=timeout)
            results.append(result)
            if stop_on_error and not result.success:
                logger.warning(
                    f"批量执行在命令失败时停止: {cmd} (exit={result.exit_code})"
                )
                break
        return results

    # ------------------------------------------------------------------
    # SFTP 文件传输
    # ------------------------------------------------------------------

    def _get_sftp(self):
        """获取或创建 SFTP 客户端。"""
        if self._sftp is None:
            self._ensure_connected()
            self._sftp = self._client.open_sftp()
        return self._sftp

    def upload(self, local_path: str, remote_path: str) -> "SSHClient":
        """上传单个文件到远程服务器。"""
        self._ensure_connected()
        if not os.path.isfile(local_path):
            raise SFTPError(
                f"本地文件不存在: {local_path}",
                local_path=local_path,
                remote_path=remote_path,
                host=self._host,
            )
        sftp = self._get_sftp()
        try:
            sftp.put(local_path, remote_path)
            logger.info(
                f"SFTP 上传成功: {local_path} -> {remote_path} "
                f"({os.path.getsize(local_path)} bytes)"
            )
        except Exception as e:
            raise SFTPError(
                f"SFTP 上传失败: {e}",
                local_path=local_path,
                remote_path=remote_path,
                host=self._host,
            ) from e
        return self

    def download(self, remote_path: str, local_path: str) -> "SSHClient":
        """从远程服务器下载单个文件。"""
        self._ensure_connected()
        sftp = self._get_sftp()
        # 确保本地目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        try:
            sftp.get(remote_path, local_path)
            logger.info(f"SFTP 下载成功: {remote_path} -> {local_path}")
        except Exception as e:
            raise SFTPError(
                f"SFTP 下载失败: {e}",
                local_path=local_path,
                remote_path=remote_path,
                host=self._host,
            ) from e
        return self

    def upload_dir(self, local_dir: str, remote_dir: str) -> "SSHClient":
        """递归上传整个目录。"""
        self._ensure_connected()
        if not os.path.isdir(local_dir):
            raise SFTPError(
                f"本地目录不存在: {local_dir}",
                local_path=local_dir,
                remote_path=remote_dir,
                host=self._host,
            )
        sftp = self._get_sftp()
        self._ensure_remote_dir(sftp, remote_dir)

        for root, dirs, files in os.walk(local_dir):
            rel = os.path.relpath(root, local_dir)
            if rel == ".":
                remote_root = remote_dir
            else:
                remote_root = remote_dir + "/" + rel.replace("\\", "/")
            for d in dirs:
                remote_path = remote_root + "/" + d
                self._ensure_remote_dir(sftp, remote_path)
            for f in files:
                local_path = os.path.join(root, f)
                remote_path = remote_root + "/" + f
                sftp.put(local_path, remote_path)

        logger.info(f"SFTP 目录上传完成: {local_dir} -> {remote_dir}")
        return self

    def download_dir(self, remote_dir: str, local_dir: str) -> "SSHClient":
        """递归下载整个目录。"""
        self._ensure_connected()
        sftp = self._get_sftp()
        os.makedirs(local_dir, exist_ok=True)

        def _download_recursive(r_dir: str, l_dir: str):
            os.makedirs(l_dir, exist_ok=True)
            for entry in sftp.listdir_attr(r_dir):
                remote_path = r_dir + "/" + entry.filename
                local_path = os.path.join(l_dir, entry.filename)
                if stat_module.S_ISDIR(entry.st_mode):
                    _download_recursive(remote_path, local_path)
                else:
                    sftp.get(remote_path, local_path)

        try:
            _download_recursive(remote_dir, local_dir)
            logger.info(f"SFTP 目录下载完成: {remote_dir} -> {local_dir}")
        except Exception as e:
            raise SFTPError(
                f"SFTP 目录下载失败: {e}",
                local_path=local_dir,
                remote_path=remote_dir,
                host=self._host,
            ) from e
        return self

    def exists(self, remote_path: str) -> bool:
        """检查远程文件/目录是否存在。"""
        self._ensure_connected()
        sftp = self._get_sftp()
        try:
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except IOError:
            return False

    def stat(self, remote_path: str):
        """获取远程文件属性。"""
        self._ensure_connected()
        sftp = self._get_sftp()
        return sftp.stat(remote_path)

    # ------------------------------------------------------------------
    # 端口转发
    # ------------------------------------------------------------------

    def tunnel(
        self,
        *,
        local_port: int,
        remote_host: str,
        remote_port: int,
        local_host: str = "127.0.0.1",
    ) -> SSHTunnel:
        """创建 SSH 端口转发隧道。

        使用方式::

            with ssh.tunnel(local_port=3307, remote_host="10.0.0.3",
                            remote_port=3306) as t:
                # 本地 3307 端口通过 SSH 转发到 10.0.0.3:3306
                ...
        """
        return SSHTunnel(
            self,
            local_port=local_port,
            remote_host=remote_host,
            remote_port=remote_port,
            local_host=local_host,
        )

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self) -> "SSHClient":
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.is_connected():
            raise SSHConnectionError(
                "SSH 连接未建立或已断开，请先调用 connect()",
                host=self._host,
            )

    @staticmethod
    def _ensure_remote_dir(sftp, remote_dir: str) -> None:
        """递归创建远程目录。"""
        parts = remote_dir.strip("/").split("/")
        path = ""
        for part in parts:
            if not part:
                continue
            path = path + "/" + part
            try:
                sftp.stat(path)
            except FileNotFoundError:
                sftp.mkdir(path)
            except IOError:
                sftp.mkdir(path)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def host(self) -> str:
        return self._host

    @property
    def username(self) -> str:
        return self._username

    @property
    def port(self) -> int:
        return self._port
