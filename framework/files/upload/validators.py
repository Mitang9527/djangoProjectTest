import os
import hashlib
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple, Set
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from loguru import logger
from .exceptions import (
    InvalidFileTypeError,
    FileTooLargeError,
    FileSecurityError
)

try:
    import magic
    _HAS_MAGIC = True
except (ImportError, OSError):
    magic = None
    _HAS_MAGIC = False
    logger.warning(
        "python-magic 未安装或 libmagic 缺失，"
        "文件 MIME 类型检测将降级为 mimetypes（基于扩展名，安全性较低）。"
        "安装 python-magic + libmagic 可恢复真实内容检测。"
    )


class FileValidator:
    """文件验证器"""

    DEFAULT_ALLOWED_TYPES = {
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/plain',
    }

    DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    DANGEROUS_EXTENSIONS = {
        '.exe', '.bat', '.cmd', '.scr', '.pif', '.com', '.dll',
        '.js', '.vbs', '.ps1', '.sh', '.php', '.jsp', '.asp', '.aspx'
    }

    def __init__(
        self,
        allowed_types: Optional[Set[str]] = None,
        max_file_size: Optional[int] = None,
        enable_virus_scan: bool = False,
        allowed_extensions: Optional[Set[str]] = None
    ):
        self.allowed_types = allowed_types or self.DEFAULT_ALLOWED_TYPES
        self.max_file_size = max_file_size or self.DEFAULT_MAX_FILE_SIZE
        self.enable_virus_scan = enable_virus_scan
        self.allowed_extensions = allowed_extensions
        self.mime_magic = magic.Magic(mime=True) if _HAS_MAGIC else None

    def validate(self, file: UploadedFile) -> Tuple[bool, Optional[str]]:
        """
        验证文件

        Returns:
            (是否通过, 错误信息)
        """
        try:
            self._validate_extension(file)
            self._validate_size(file)
            self._validate_mime_type(file)
            if self.enable_virus_scan:
                self._scan_virus(file)
            return True, None
        except FileSecurityError as e:
            logger.warning(f"文件安全验证失败: {str(e)}")
            return False, str(e)
        except Exception as e:
            logger.error(f"文件验证异常: {str(e)}")
            return False, str(e)

    def _validate_extension(self, file: UploadedFile):
        """验证文件扩展名"""
        ext = Path(file.name).suffix.lower()
        
        if ext in self.DANGEROUS_EXTENSIONS:
            raise FileSecurityError(f"不允许的文件扩展名: {ext}")
        
        if self.allowed_extensions and ext not in self.allowed_extensions:
            raise InvalidFileTypeError(f"不允许的文件扩展名: {ext}")

    def _validate_size(self, file: UploadedFile):
        """验证文件大小"""
        file_size = file.size
        if file_size > self.max_file_size:
            raise FileTooLargeError(
                f"文件过大 ({file_size / 1024 / 1024:.2f}MB), "
                f"最大允许 {self.max_file_size / 1024 / 1024:.2f}MB"
            )

    def _validate_mime_type(self, file: UploadedFile):
        """验证 MIME 类型（优先使用 python-magic 检测真实文件类型，降级为 mimetypes）"""
        file.seek(0)
        content = file.read(2048)
        file.seek(0)

        if not content:
            raise FileSecurityError("文件内容为空")

        if self.mime_magic is not None:
            detected_mime = self.mime_magic.from_buffer(content)
        else:
            guessed, _ = mimetypes.guess_type(file.name)
            detected_mime = guessed or "application/octet-stream"

        if detected_mime not in self.allowed_types:
            raise InvalidFileTypeError(
                f"不允许的文件类型: {detected_mime}, "
                f"允许的类型: {', '.join(self.allowed_types)}"
            )

    def _scan_virus(self, file: UploadedFile):
        """
        扫描文件病毒（可选功能）
        这里提供一个基础实现，实际生产环境可以接入 ClamAV 等专业病毒扫描服务
        """
        file.seek(0)
        content = file.read()
        file.seek(0)
        
        self._check_suspicious_patterns(content)

    def _check_suspicious_patterns(self, content: bytes):
        """检查可疑的二进制模式"""
        suspicious_patterns = [
            b'\x4d\x5a',  # PE 可执行文件头
            b'<?php',
            b'<%',
            b'<script',
        ]
        
        for pattern in suspicious_patterns:
            if pattern in content:
                logger.warning(f"检测到可疑模式: {pattern}")


def validate_file_type(
    file: UploadedFile,
    allowed_types: Optional[Set[str]] = None
) -> bool:
    """
    便捷函数：验证文件类型
    """
    validator = FileValidator(allowed_types=allowed_types)
    is_valid, error = validator.validate(file)
    if not is_valid:
        raise InvalidFileTypeError(error)
    return True


def validate_file_size(
    file: UploadedFile,
    max_size: Optional[int] = None
) -> bool:
    """
    便捷函数：验证文件大小
    """
    validator = FileValidator(max_file_size=max_size)
    is_valid, error = validator.validate(file)
    if not is_valid:
        raise FileTooLargeError(error)
    return True


def scan_file_for_virus(file: UploadedFile) -> bool:
    """
    便捷函数：扫描病毒
    """
    validator = FileValidator(enable_virus_scan=True)
    is_valid, error = validator.validate(file)
    if not is_valid:
        raise FileSecurityError(error)
    return True


def safe_file_upload(
    file: UploadedFile,
    upload_dir: str,
    validator: Optional[FileValidator] = None,
    random_filename: bool = True
) -> str:
    """
    安全文件上传函数

    Args:
        file: 上传的文件对象
        upload_dir: 上传目录
        validator: 文件验证器
        random_filename: 是否使用随机文件名

    Returns:
        保存后的文件路径
    """
    if validator is None:
        validator = FileValidator()

    is_valid, error = validator.validate(file)
    if not is_valid:
        raise FileSecurityError(error)

    upload_path = Path(settings.MEDIA_ROOT) / upload_dir
    upload_path.mkdir(parents=True, exist_ok=True)

    if random_filename:
        ext = Path(file.name).suffix.lower()
        filename = f"{hashlib.md5(str(os.urandom(16)).encode()).hexdigest()}{ext}"
    else:
        filename = file.name

    file_path = upload_path / filename
    with open(file_path, 'wb+') as destination:
        for chunk in file.chunks():
            destination.write(chunk)

    logger.info(f"文件已安全保存: {file_path}")
    return str(file_path)
