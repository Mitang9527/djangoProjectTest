"""企业级 TCP 客户端封装。

基于标准库 socket，提供：
- 上下文管理器（with 语句自动关闭）
- 可配置的连接 / 收发超时
- 自动重连（可配置重试次数 + 退避间隔）
- str / bytes 双模式收发
- send_and_receive 请求-响应模式（一发一收）
- 连接状态检查
- loguru 日志
- 自定义异常体系

使用示例::

    from utils.ConnectServer import TCPClient

    # 基本用法
    with TCPClient("127.0.0.1", 8080, timeout=10) as tcp:
        tcp.send("Hello, Server!")
        response = tcp.receive()
        print(response)

    # 请求-响应模式
    with TCPClient("127.0.0.1", 9000) as tcp:
        resp = tcp.send_and_receive("PING", expect_bytes=False)
        print(resp)

    # 二进制模式
    with TCPClient("127.0.0.1", 9001) as tcp:
        tcp.send(b"\\x01\\x02\\x03")
        data = tcp.receive(expect_bytes=True)
        print(data.hex())
"""

from __future__ import annotations

import socket
import time
from typing import Optional, Union

from loguru import logger

from .exceptions import (
    TCPConfigError,
    TCPConnectionError,
    TCPError,
    TCPReceiveError,
    TCPSendError,
    TCPTimeoutError,
)

__all__ = ["TCPClient"]


class TCPClient:
    """企业级 TCP 客户端。

    Args:
        host: 目标服务器地址。
        port: 目标服务器端口。
        timeout: 默认超时（秒），用于连接 + 收发。
        connect_timeout: 连接超时（秒），优先于 timeout。
        send_timeout: 发送超时（秒），优先于 timeout。
        recv_timeout: 接收超时（秒），优先于 timeout。
        max_retries: 连接失败时的最大重试次数（0 = 不重试）。
        retry_delay: 重试间隔（秒）。
        auto_reconnect: 操作失败时是否自动重连。
        encoding: str 模式下的编码，默认 utf-8。
        buffer_size: 默认接收缓冲区大小。
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 30.0,
        connect_timeout: Optional[float] = None,
        send_timeout: Optional[float] = None,
        recv_timeout: Optional[float] = None,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        auto_reconnect: bool = True,
        encoding: str = "utf-8",
        buffer_size: int = 4096,
    ):
        if not host:
            raise TCPConfigError("host 不能为空")
        if not isinstance(port, int) or port <= 0 or port > 65535:
            raise TCPConfigError(f"port 无效: {port}（应为 1-65535 的整数）")

        self._host = host
        self._port = port
        self._timeout = timeout
        self._connect_timeout = connect_timeout or timeout
        self._send_timeout = send_timeout or timeout
        self._recv_timeout = recv_timeout or timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._auto_reconnect = auto_reconnect
        self._encoding = encoding
        self._buffer_size = buffer_size

        self._socket: Optional[socket.socket] = None
        self._connected = False

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    # ---- 工厂方法：便于子类覆盖 / 测试中 mock ----
    def _new_socket(self) -> "socket.socket":
        """创建新 socket。子类可重写；测试可 patch。

        返回一个未连接的 socket。调用方负责 settimeout + connect。
        """
        return socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect(self) -> "TCPClient":
        """建立 TCP 连接。

        失败时根据 max_retries 重试。
        """
        if self._connected:
            return self

        last_exc: Optional[Exception] = None
        total_attempts = self._max_retries + 1

        for attempt in range(1, total_attempts + 1):
            try:
                sock = self._new_socket()
                sock.settimeout(self._connect_timeout)
                sock.connect((self._host, self._port))

                # 连接成功后设置收发超时
                sock.settimeout(self._recv_timeout)

                self._socket = sock
                self._connected = True
                logger.info(f"TCP 已连接: {self._host}:{self._port}")
                return self

            except socket.timeout as e:
                last_exc = TCPTimeoutError(
                    f"TCP 连接超时 ({self._connect_timeout}s): "
                    f"{self._host}:{self._port}",
                    timeout=self._connect_timeout,
                    host=self._host,
                    port=self._port,
                )

            except (ConnectionRefusedError, socket.error) as e:
                last_exc = TCPConnectionError(
                    f"TCP 连接失败: {self._host}:{self._port} - {e}",
                    host=self._host,
                    port=self._port,
                )

            # 未到上限则等待重试
            if attempt < total_attempts:
                logger.warning(
                    f"TCP 连接失败 (attempt {attempt}/{total_attempts}), "
                    f"{self._retry_delay}s 后重试..."
                )
                time.sleep(self._retry_delay)

        raise last_exc  # type: ignore[misc]

    def disconnect(self) -> None:
        """关闭 TCP 连接。"""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        if self._connected:
            self._connected = False
            logger.info(f"TCP 已断开: {self._host}:{self._port}")

    def close(self) -> None:
        """disconnect 的别名。"""
        self.disconnect()

    def is_connected(self) -> bool:
        """检查连接是否仍然有效。

        通过 getpeername 判断 socket 是否处于连接状态。
        """
        if not self._connected or self._socket is None:
            return False
        try:
            self._socket.getpeername()
            return True
        except socket.error:
            return False

    def reconnect(self) -> "TCPClient":
        """断开并重新连接。"""
        self.disconnect()
        return self.connect()

    # ------------------------------------------------------------------
    # 数据收发
    # ------------------------------------------------------------------

    def send(
        self,
        data: Union[str, bytes],
        *,
        encoding: Optional[str] = None,
    ) -> int:
        """发送数据到服务器。

        Args:
            data: 要发送的数据（str 或 bytes）。
            encoding: str 数据的编码（默认使用实例 encoding）。

        Returns:
            已发送的字节数。
        """
        self._ensure_connected()

        if isinstance(data, str):
            payload = data.encode(encoding or self._encoding)
        elif isinstance(data, bytes):
            payload = data
        else:
            raise TCPSendError(
                f"不支持的数据类型: {type(data).__name__}（期望 str 或 bytes）",
                host=self._host,
                port=self._port,
            )

        self._socket.settimeout(self._send_timeout)
        try:
            sent = self._socket.sendall(payload)
            # sendall 返回 None 表示全部发送成功
            sent_bytes = len(payload) if sent is None else sent
            logger.debug(
                f"TCP 发送 {sent_bytes} bytes -> {self._host}:{self._port}"
            )
            return sent_bytes

        except socket.timeout as e:
            logger.error(f"TCP 发送超时: {self._host}:{self._port}")
            if self._auto_reconnect:
                self._handle_disconnect()
            raise TCPTimeoutError(
                f"TCP 发送超时 ({self._send_timeout}s)",
                timeout=self._send_timeout,
                host=self._host,
                port=self._port,
            ) from e

        except socket.error as e:
            logger.error(f"TCP 发送失败: {e}")
            if self._auto_reconnect:
                self._handle_disconnect()
            raise TCPSendError(
                f"TCP 发送失败: {e}",
                host=self._host,
                port=self._port,
            ) from e

    def receive(
        self,
        buffer_size: Optional[int] = None,
        *,
        expect_bytes: bool = False,
        encoding: Optional[str] = None,
    ) -> Union[str, bytes]:
        """接收来自服务器的数据。

        Args:
            buffer_size: 接收缓冲区大小（默认使用实例 buffer_size）。
            expect_bytes: True 返回 bytes，False 返回 str（解码）。
            encoding: str 模式的解码编码。

        Returns:
            接收到的数据（str 或 bytes）。
        """
        self._ensure_connected()

        buf = buffer_size or self._buffer_size
        self._socket.settimeout(self._recv_timeout)

        try:
            data = self._socket.recv(buf)
        except socket.timeout as e:
            logger.error(f"TCP 接收超时: {self._host}:{self._port}")
            raise TCPTimeoutError(
                f"TCP 接收超时 ({self._recv_timeout}s)",
                timeout=self._recv_timeout,
                host=self._host,
                port=self._port,
            ) from e

        except socket.error as e:
            logger.error(f"TCP 接收失败: {e}")
            if self._auto_reconnect:
                self._handle_disconnect()
            raise TCPReceiveError(
                f"TCP 接收失败: {e}",
                host=self._host,
                port=self._port,
            ) from e

        if not data:
            # 对端关闭连接
            logger.warning(f"TCP 对端关闭连接: {self._host}:{self._port}")
            self._connected = False
            if self._auto_reconnect:
                self._handle_disconnect()
            raise TCPConnectionError(
                f"TCP 对端已关闭连接: {self._host}:{self._port}",
                host=self._host,
                port=self._port,
            )

        logger.debug(f"TCP 接收 {len(data)} bytes <- {self._host}:{self._port}")

        if expect_bytes:
            return data
        return data.decode(encoding or self._encoding, errors="replace")

    def send_and_receive(
        self,
        data: Union[str, bytes],
        *,
        buffer_size: Optional[int] = None,
        expect_bytes: bool = False,
        encoding: Optional[str] = None,
    ) -> Union[str, bytes]:
        """发送数据并等待接收响应（请求-响应模式）。

        Args:
            data: 要发送的数据。
            buffer_size: 接收缓冲区大小。
            expect_bytes: True 返回 bytes。
            encoding: 解码编码。

        Returns:
            接收到的响应数据。
        """
        self.send(data, encoding=encoding)
        return self.receive(
            buffer_size=buffer_size,
            expect_bytes=expect_bytes,
            encoding=encoding,
        )

    # ------------------------------------------------------------------
    # 上下文管理器
    # ------------------------------------------------------------------

    def __enter__(self) -> "TCPClient":
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.is_connected():
            if self._auto_reconnect:
                logger.info("TCP 连接已断开，尝试自动重连...")
                self.connect()
            else:
                raise TCPConnectionError(
                    "TCP 连接未建立，请先调用 connect()",
                    host=self._host,
                    port=self._port,
                )

    def _handle_disconnect(self) -> None:
        """处理连接断开（标记为断开，不自动重连，由后续操作触发重连）。"""
        self._connected = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def encoding(self) -> str:
        return self._encoding

    @property
    def buffer_size(self) -> int:
        return self._buffer_size
