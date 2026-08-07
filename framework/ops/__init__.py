# sync-init: skip
"""远程连接服务聚合包。

统一管理 SSH / TCP / HTTP 等远程连接客户端及异常。

模块结构::

    connect_server/
    +-- exceptions.py    # 统一异常体系（基类 TransportError，SSH/TCP 业务基类派生于它）
    +-- ssh_client.py    # SSH 客户端（基于 paramiko）
    +-- tcp_client.py    # TCP 客户端（基于 stdlib socket）

异常体系::

    TransportError                   -- 所有远程连接异常的根
    +-- ConfigError                  -- 共享：配置错误
    +-- ConnectionError              -- 共享：连接失败
    |   +-- AuthError                -- 共享：认证失败
    +-- TimeoutError                 -- 共享：超时
    +-- SSHError(TransportError)     -- SSH 业务基类
    |   +-- SSHConfigError           -- SSH 配置错
    |   +-- SSHConnectionError       -- SSH 连接错
    |   +-- SSHAuthError             -- SSH 认证错
    |   +-- SSHTimeoutError          -- SSH 超时
    |   +-- SSHCommandError          -- SSH 命令失败
    |   +-- SFTPError                -- SFTP 文件传输错
    +-- TCPError(TransportError)     -- TCP 业务基类
        +-- TCPConfigError           -- TCP 配置错
        +-- TCPConnectionError       -- TCP 连接错
        +-- TCPTimeoutError          -- TCP 超时
        +-- TCPSendError             -- TCP 发送错
        +-- TCPReceiveError          -- TCP 接收错

快速使用::

    from framework.ops import SSHClient, TCPClient, ConfigError, TimeoutError

    # SSH
    with SSHClient("10.0.0.1", "root", password="xxx") as ssh:
        result = ssh.execute("uname -a")
        print(result.stdout)
        ssh.upload("/local/app.py", "/remote/app.py")

    # SSH 隧道
    with ssh.tunnel(local_port=3307, remote_host="db.internal",
                    remote_port=3306) as tunnel:
        # 本地 3307 端口经 SSH 转发到 db.internal:3306
        ...

    # TCP
    with TCPClient("127.0.0.1", 8080) as tcp:
        tcp.send("Hello")
        response = tcp.receive()
        print(response)

    # TCP 请求-响应
    with TCPClient("127.0.0.1", 9000) as tcp:
        resp = tcp.send_and_receive("PING")
        print(resp)

    # 统一异常捕获——一个 except 抓全部远程连接异常
    try:
        ...
    except ConfigError:
        ...  # SSH/TCP/HTTP 任一配置错都走这里

迁移说明：
- 旧 `framework/ssh/` 和 `framework/tcp/` 已删除，全部归类到本包
- 旧 `ssh_exceptions.py` / `tcp_exceptions.py` 已合并为 `exceptions.py`
- 调用方需将 `from framework.ssh import X` 改为 `from framework.ops import X`
- 旧 except SSHError / except TCPError 仍兼容（SSHError/TCPError 仍为合法类型）
- HTTP 客户端请直接用 `framework.http_client`（之前已封装），本包通过转发 re-export 保持兼容
"""

# SSH 客户端
from .ssh_client import CommandResult, SSHClient, SSHTunnel

# TCP 客户端
from .tcp_client import TCPClient

# 统一异常体系
from .exceptions import (
    # 基类 + 共享子类
    AuthError,
    ConfigError,
    ConnectionError,
    SFTPError,
    SSHAuthError,
    SSHCommandError,
    SSHConfigError,
    SSHConnectionError,
    SSHError,
    SSHTimeoutError,
    TCPConfigError,
    TCPConnectionError,
    TCPError,
    TCPReceiveError,
    TCPSendError,
    TCPTimeoutError,
    TimeoutError,
    TransportError,
)

# HTTP 客户端（从 framework.http_client 转发，向后兼容旧项目 requestsHTTP.py 风格）
try:
    from framework.http_client import (
        AuthInterceptor,
        ConnectionError_ as HTTPConnectionError,
        HTTPClient,
        HTTPClientError,
        HTTPError,
        HTTPNetworkError,
        InterceptorError,
        InvalidConfigError,
        LoggingInterceptor,
        RetryExhaustedError,
        StatusError,
        TimingInterceptor,
        TimeoutError as HTTPTimeoutError,
        get_default_client,
    )
except ImportError:  # pragma: no cover
    HTTPClient = None  # type: ignore[assignment]

__all__ = [
    # 客户端
    "SSHClient",
    "SSHTunnel",
    "CommandResult",
    "TCPClient",
    # 统一异常（基类 + 共享 + 业务）
    "TransportError",
    "ConfigError",
    "ConnectionError",
    "AuthError",
    "TimeoutError",
    "SSHError",
    "SSHConfigError",
    "SSHConnectionError",
    "SSHAuthError",
    "SSHTimeoutError",
    "SSHCommandError",
    "SFTPError",
    "TCPError",
    "TCPConfigError",
    "TCPConnectionError",
    "TCPTimeoutError",
    "TCPSendError",
    "TCPReceiveError",
    # HTTP（来自 framework.http_client）
    "HTTPClient",
    "HTTPError",
    "HTTPClientError",
    "HTTPNetworkError",
    "HTTPTimeoutError",
    "HTTPConnectionError",
    "StatusError",
    "RetryExhaustedError",
    "InterceptorError",
    "InvalidConfigError",
    "LoggingInterceptor",
    "TimingInterceptor",
    "AuthInterceptor",
    "get_default_client",
]
