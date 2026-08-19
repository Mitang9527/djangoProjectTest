"""
framework/storage 异常体系
================================

存储后端统一异常。所有后端（local / oss / s3）抛出的错误都会归一到这里，
调用方只需捕获 StorageError 即可，无需关心具体是哪个后端。
"""


class StorageError(Exception):
    """存储操作基础异常（所有存储错误的父类）。"""

    #: 是否可重试（网络抖动/限流等）。子类可覆盖。
    retryable: bool = False


class StorageConfigError(StorageError):
    """配置错误：缺少必要参数、backend 不支持等。

    这类错误通常是部署/配置问题，重试无意义。
    """


class StorageConnectionError(StorageError):
    """无法连接到存储后端（网络/鉴权失败）。"""

    retryable = True


class StorageNotFoundError(StorageError):
    """对象不存在（get/delete/stat 时 key 未找到）。"""


class StorageAlreadyExistsError(StorageError):
    """对象已存在且不允许覆盖。"""


class StorageUploadError(StorageError):
    """上传失败（流式中断、校验和不匹配等）。"""

    retryable = True


class StorageDownloadError(StorageError):
    """下载失败。"""

    retryable = True


class StorageBackendUnavailable(StorageError):
    """请求的 backend 依赖的 SDK 未安装，或底层服务不可达且无法降级。"""

    retryable = True
