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

    # MIME 白名单（与扩展名同步）：有 magic 按真实内容检测，否则 mimetypes 猜扩展名。
    # 部分扩展（.csv/.rtf/.avi）不同平台 mimetypes 猜测不同，此处按 Windows 实测值对齐。
    DEFAULT_ALLOWED_TYPES = {
        # 图片
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'image/bmp',
        'image/x-icon',
        'image/tiff',
        'image/heic',          # .heic
        'image/heif',          # .heif
        'image/avif',          # .avif
        # 视频
        'video/mp4',
        'video/webm',
        'video/quicktime',
        'video/avi',
        'video/x-matroska',
        'video/x-flv',
        'video/x-ms-wmv',
        'video/x-m4v',
        'video/ogg',           # .ogv
        'video/mpeg',          # .mpeg / .mpg
        'video/3gpp',          # .3gp
        'video/mp2t',          # .ts (MPEG transport stream)
        'video/vnd.dlna.mpeg-tts',  # .ts (Windows mimetypes 实际值)
        # 音频
        'audio/mpeg',
        'audio/wav',
        'audio/ogg',
        'audio/vnd.dlna.adts',
        'audio/x-flac',
        'audio/mp4',
        'audio/opus',          # .opus
        'audio/midi',          # .mid / .midi
        'audio/mid',           # .mid / .midi (Windows mimetypes 实际值)
        # 文档 / 数据 / 归档
        'application/pdf',
        'application/msword',                                         # .doc / .rtf
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',                                   # .xls / .csv
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'text/plain',
        'text/csv',
        'text/markdown',
        'text/xml',
        'application/json',
        'application/x-zip-compressed',
        # OpenDocument / 电子书 / 日历名片 / 表格配置
        'application/vnd.oasis.opendocument.text',          # .odt
        'application/vnd.oasis.opendocument.spreadsheet',   # .ods
        'application/vnd.oasis.opendocument.presentation',  # .odp
        'application/epub+zip',                             # .epub
        'application/epub',                                 # .epub (Windows mimetypes 实际值)
        'text/calendar',                                   # .ics
        'text/vcard', 'text/x-vcard',                      # .vcf
        'text/tab-separated-values',                       # .tsv
        'application/yaml', 'text/yaml', 'application/x-yaml',  # .yaml / .yml
        # 归档（与已放行的 .zip 同性质；后端若解压需防 zip bomb）
        'application/x-7z-compressed',                     # .7z
        'application/x-tar',                               # .tar
        'application/gzip', 'application/x-gzip',          # .gz / .tgz
        'application/vnd.rar', 'application/x-rar-compressed',  # .rar
        'application/x-compressed',                            # .7z / .rar (Windows mimetypes 实际值)
        # 字体（web 项目常需）
        'font/woff', 'application/font-woff', 'application/x-font-woff',        # .woff
        'font/woff2', 'application/font-woff2', 'application/x-font-woff2',    # .woff2
        'font/ttf', 'application/x-font-ttf',                                  # .ttf
        'font/otf', 'application/x-font-otf',                                  # .otf
    }

    DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # 视频单独放宽：默认 100MB，可通过 settings.FILE_UPLOAD_MAX_VIDEO_FILE_SIZE 覆盖
    DEFAULT_MAX_VIDEO_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB

    # 白名单铁律：绝不黑名单（.php5/.phtml/.shtml/.cgi/.pl/.py/.htaccess 等无数变体可绕过），只放行已知安全格式
    # 图片；⚠️ SVG 刻意不纳入：image/svg+xml 可内嵌 <script> 是 XSS 向量，确需须先 XML 净化（bleach/defusedxml）
    DEFAULT_IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.ico', '.tiff', '.tif',
        '.heic', '.heif', '.avif',
    }

    # 视频：主流容器格式
    DEFAULT_VIDEO_EXTENSIONS = {
        '.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v',
        '.ogv', '.mpeg', '.mpg', '.3gp', '.ts',
    }

    # 音频：常与视频一并归类为媒体文件
    DEFAULT_AUDIO_EXTENSIONS = {
        '.mp3', '.wav', '.ogg', '.aac', '.flac', '.m4a',
        '.opus', '.oga', '.mid', '.midi',
    }

    # 文档 / 数据 / 归档 / 字体等常见格式
    DEFAULT_DOC_EXTENSIONS = {
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.txt', '.csv', '.rtf', '.md', '.json', '.xml', '.zip',
        '.odt', '.ods', '.odp', '.epub', '.ics', '.vcf', '.tsv',
        '.yaml', '.yml',
        '.7z', '.tar', '.gz', '.tgz', '.rar',
        '.woff', '.woff2', '.ttf', '.otf',
    }

    # 通用白名单 = 图片 ∪ 视频 ∪ 音频 ∪ 文档
    DEFAULT_ALLOWED_EXTENSIONS = (
        DEFAULT_IMAGE_EXTENSIONS
        | DEFAULT_VIDEO_EXTENSIONS
        | DEFAULT_AUDIO_EXTENSIONS
        | DEFAULT_DOC_EXTENSIONS
    )

    def __init__(
        self,
        allowed_types: Optional[Set[str]] = None,
        max_file_size: Optional[int] = None,
        enable_virus_scan: bool = False,
        allowed_extensions: Optional[Set[str]] = None,
        max_video_file_size: Optional[int] = None
    ):
        self.allowed_types = allowed_types or self.DEFAULT_ALLOWED_TYPES
        self.max_file_size = max_file_size or self.DEFAULT_MAX_FILE_SIZE

        # 视频类单独上限：传入优先，否则用默认 100MB 放宽值
        self.max_video_file_size = max_video_file_size or self.DEFAULT_MAX_VIDEO_FILE_SIZE
        self.enable_virus_scan = enable_virus_scan

        # 未显式传入时启用默认严格白名单，绝不退化为「无限制」
        self.allowed_extensions = allowed_extensions or self.DEFAULT_ALLOWED_EXTENSIONS
        self.mime_magic = magic.Magic(mime=True) if _HAS_MAGIC else None

    @staticmethod
    def _is_video(file: UploadedFile) -> bool:
        """按扩展名判断是否为视频文件（与白名单共用 DEFAULT_VIDEO_EXTENSIONS）。"""
        _, ext = os.path.splitext(file.name)
        return ext.lower() in FileValidator.DEFAULT_VIDEO_EXTENSIONS

    def validate(self, file: UploadedFile) -> Tuple[bool, Optional[str]]:
        """验证文件：扩展名 → 大小 → MIME →（可选）病毒扫描；返回 (是否通过, 错误信息)。"""
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
        """验证扩展名（严格白名单 + 小写归一化，使 .JPG 与 .jpg 等价识别）。"""
        # os.path.splitext 兼容无后缀 / 多点的文件名（a.b.exe -> .exe）
        _, ext = os.path.splitext(file.name)
        ext = ext.lower()

        allowed = self.allowed_extensions
        if ext not in allowed:
            label = ext or '(无后缀)'
            raise InvalidFileTypeError(
                f"不允许的文件扩展名: {label}，"
                f"仅允许: {', '.join(sorted(allowed))}"
            )

    def _validate_size(self, file: UploadedFile):
        """验证大小：视频类用 max_video_file_size（默认 100MB），其余 max_file_size（默认 10MB）。"""
        file_size = file.size
        effective_limit = (
            self.max_video_file_size if self._is_video(file) else self.max_file_size
        )
        if file_size > effective_limit:
            limit_label = "视频类" if effective_limit is self.max_video_file_size else "通用"
            raise FileTooLargeError(
                f"文件过大 ({file_size / 1024 / 1024:.2f}MB), "
                f"{limit_label}最大允许 {effective_limit / 1024 / 1024:.2f}MB"
            )

    def _validate_mime_type(self, file: UploadedFile):
        """验证 MIME 类型（优先使用 python-magic 检测真实文件类型，降级为 mimetypes）"""
        file.seek(0)
        content = file.read(2048)
        file.seek(0)

        if not content:
            raise FileSecurityError("文件内容为空")

        if self.mime_magic is not None:
            # python-magic 可用：按真实文件内容检测（权威闸门）
            detected_mime = self.mime_magic.from_buffer(content)
            # 内容无法判定（空串/None）时降级用扩展名猜测，避免误拒合法文件
            if not detected_mime:
                guessed, _ = mimetypes.guess_type(file.name)
                detected_mime = guessed
            if detected_mime:
                if detected_mime not in self.allowed_types:
                    raise InvalidFileTypeError(
                        f"不允许的文件类型: {detected_mime}, "
                        f"允许的类型: {', '.join(self.allowed_types)}"
                    )
            # detected_mime 仍为 None → 扩展名白名单已批准，放过
        else:
            # 降级：mimetypes 猜不出时扩展名白名单已先批准，直接放过（如 .webp/.flv/.md）
            guessed, _ = mimetypes.guess_type(file.name)
            if not guessed:
                return
            if guessed not in self.allowed_types:
                raise InvalidFileTypeError(
                    f"不允许的文件类型: {guessed}, "
                    f"允许的类型: {', '.join(self.allowed_types)}"
                )

    def _scan_virus(self, file: UploadedFile):
        """扫描病毒（可选）：基础实现，生产可接入 ClamAV 等专业服务。"""
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
    """便捷：验证文件类型（不通过抛 InvalidFileTypeError）。"""
    validator = FileValidator(allowed_types=allowed_types)
    is_valid, error = validator.validate(file)
    if not is_valid:
        raise InvalidFileTypeError(error)
    return True


def validate_file_size(
    file: UploadedFile,
    max_size: Optional[int] = None
) -> bool:
    """便捷：验证文件大小（不通过抛 FileTooLargeError）。"""
    validator = FileValidator(max_file_size=max_size)
    is_valid, error = validator.validate(file)
    if not is_valid:
        raise FileTooLargeError(error)
    return True


def scan_file_for_virus(file: UploadedFile) -> bool:
    """便捷：扫描病毒（不通过抛 FileSecurityError）。"""
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
    """安全上传：验证后按 MEDIA_ROOT/upload_dir 保存，支持随机文件名。

    :param file: 上传文件对象；upload_dir: 上传子目录
    :param validator: 文件验证器（默认 FileValidator()）；random_filename: 是否用随机名
    :return: 保存后的文件路径（绝对路径，如需访问 URL 用 relative_media_url 转换）
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


def relative_media_url(abs_path: str) -> str:
    """将 MEDIA_ROOT 下绝对路径转为相对 MEDIA_URL 的访问地址（统一正斜杠）。

    避免两个问题：① 回吐绝对路径暴露服务器目录结构（信息泄露）；② Windows 反斜杠混入 URL。
    """
    abs_path = os.path.abspath(abs_path)
    media_root = os.path.abspath(str(settings.MEDIA_ROOT))
    rel = os.path.relpath(abs_path, media_root)
    # 统一为正斜杠，保证跨平台 URL 规范
    rel = rel.replace(os.sep, '/')
    media_url = str(settings.MEDIA_URL).strip('/')
    return f"{media_url}/{rel}" if media_url else rel
