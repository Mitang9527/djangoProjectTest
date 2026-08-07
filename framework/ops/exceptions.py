"""远程连接服务统一异常体系。

覆盖 SSH / TCP / HTTP 等所有连接场景的失败分类。

层次结构::

    TransportError                       -- 统一基类（所有远程连接异常的根）
    +-- ConfigError                      -- 共享：配置错误（缺 host/port/参数）
    +-- ConnectionError                  -- 共享：连接失败（超时/拒绝/重置）
    |   +-- AuthError                    -- 共享：认证失败（密码/密钥错）
    +-- TimeoutError                     -- 共享：操作超时（连接/收发/命令）

    # SSH 特有
    +-- SSHError(TransportError)         -- SSH 业务基类
    |   +-- SSHCommandError              -- SSH 命令执行失败（exit_code != 0）
    |   +-- SFTPError                    -- SFTP 文件传输失败

    # TCP 特有
    +-- TCPError(TransportError)         -- TCP 业务基类
        +-- TCPSendError                 -- TCP 发送失败
        +-- TCPReceiveError              -- TCP 接收失败

设计要点：
1. **共享子类 + 业务子类**两层：调用方既可精细捕获（SSHCommandError），
   也可大范围捕获（ConfigError 一网打尽 SSH/TCP/HTTP 的所有配置错）
2. **基类 TransportError**：避免和 stdlib builtins.ConnectionError 同名冲突
3. **业务基类 SSHError/TCPError**：派生于 TransportError，保留模块语义；
   旧代码 except SSHError / except TCPError 不受影响
4. **基类承载上下文**：host/port/timeout/command/exit_code/... 都在基类/子类
   上挂载，调用方异常 handler 可直接读
"""

from __future__ import annotations

from typing import Optional


# ============================================================================
# 第一层：统一基类
# ============================================================================

class TransportError(Exception):
    """所有远程连接异常的统一基类。

    承载连接上下文（host/port），子类按需扩展。
    """

    def __init__(self, message: str, *, host: Optional[str] = None,
                 port: Optional[int] = None):
        self.host = host
        self.port = port
        super().__init__(message)


# ============================================================================
# 第二层：跨协议共享子类
# ============================================================================

class ConfigError(TransportError):
    """配置错误，如缺少必填参数。"""


class ConnectionError(TransportError):
    """连接失败（超时/拒绝/重置）。"""


class AuthError(ConnectionError):
    """认证失败（密码/密钥错）。"""


class TimeoutError(TransportError):
    """操作超时（连接/收发/命令执行）。"""

    def __init__(self, message: str, *, timeout: Optional[float] = None,
                 host: Optional[str] = None, port: Optional[int] = None):
        self.timeout = timeout
        super().__init__(message, host=host, port=port)


# ============================================================================
# 第三层：SSH 业务异常
# ============================================================================

class SSHError(TransportError):
    """SSH 操作业务基类（兼容旧 except SSHError 调用方）。"""


class SSHConfigError(ConfigError, SSHError):
    """SSH 配置错误（缺 host/username/key_filename）。"""


class SSHConnectionError(ConnectionError, SSHError):
    """SSH 连接失败。"""


class SSHAuthError(AuthError, SSHError):
    """SSH 认证失败。"""


class SSHTimeoutError(TimeoutError, SSHError):
    """SSH 操作超时（连接/命令执行）。"""


class SSHCommandError(SSHError):
    """SSH 命令执行失败（exit_code != 0）。

    携带 command/exit_code/stdout/stderr 供调用方诊断。
    """

    def __init__(self, message: str, *, command: str = "",
                 exit_code: int = -1, stdout: str = "",
                 stderr: str = "", host: Optional[str] = None):
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message, host=host)


class SFTPError(SSHError):
    """SFTP 文件传输失败。"""

    def __init__(self, message: str, *, local_path: str = "",
                 remote_path: str = "", host: Optional[str] = None):
        self.local_path = local_path
        self.remote_path = remote_path
        super().__init__(message, host=host)


# ============================================================================
# 第四层：TCP 业务异常
# ============================================================================

class TCPError(TransportError):
    """TCP 操作业务基类（兼容旧 except TCPError 调用方）。"""


class TCPConfigError(ConfigError, TCPError):
    """TCP 配置错误（缺 host/port）。"""


class TCPConnectionError(ConnectionError, TCPError):
    """TCP 连接失败。"""


class TCPTimeoutError(TimeoutError, TCPError):
    """TCP 操作超时。"""


class TCPSendError(TCPError):
    """TCP 发送数据失败。"""


class TCPReceiveError(TCPError):
    """TCP 接收数据失败。"""


__all__ = [
    # 统一基类 + 共享子类
    "TransportError",
    "ConfigError",
    "ConnectionError",
    "AuthError",
    "TimeoutError",
    # SSH
    "SSHError",
    "SSHConfigError",
    "SSHConnectionError",
    "SSHAuthError",
    "SSHTimeoutError",
    "SSHCommandError",
    "SFTPError",
    # TCP
    "TCPError",
    "TCPConfigError",
    "TCPConnectionError",
    "TCPTimeoutError",
    "TCPSendError",
    "TCPReceiveError",
]
