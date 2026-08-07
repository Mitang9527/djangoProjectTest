class FileUploadError(Exception):
    """文件上传基础异常"""
    pass


class InvalidFileTypeError(FileUploadError):
    """无效的文件类型异常"""
    pass


class FileTooLargeError(FileUploadError):
    """文件过大异常"""
    pass


class FileSecurityError(FileUploadError):
    """文件安全异常"""
    pass
