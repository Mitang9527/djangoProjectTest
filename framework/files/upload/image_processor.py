import os
import hashlib
from pathlib import Path
from typing import Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont, ImageOps
from django.conf import settings
from loguru import logger


class ImageProcessor:
    """图片处理器 - 提供压缩、水印等功能"""

    DEFAULT_MAX_WIDTH = 1920
    DEFAULT_MAX_HEIGHT = 1080
    DEFAULT_QUALITY = 85
    SUPPORTED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}

    def __init__(
        self,
        max_width: int = DEFAULT_MAX_WIDTH,
        max_height: int = DEFAULT_MAX_HEIGHT,
        quality: int = DEFAULT_QUALITY,
        keep_exif: bool = False
    ):
        self.max_width = max_width
        self.max_height = max_height
        self.quality = quality
        self.keep_exif = keep_exif

    def compress_image(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        format: Optional[str] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: Optional[int] = None
    ) -> str:
        """
        压缩图片

        Args:
            input_path: 输入图片路径
            output_path: 输出图片路径（可选）
            format: 输出格式（可选）
            max_width: 最大宽度（可选）
            max_height: 最大高度（可选）
            quality: 压缩质量 0-100（可选）

        Returns:
            输出图片路径
        """
        max_width = max_width or self.max_width
        max_height = max_height or self.max_height
        quality = quality or self.quality

        input_path = Path(input_path)
        
        if not input_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {input_path}")

        if output_path is None:
            ext = input_path.suffix.lower()
            filename = f"{hashlib.md5(str(input_path).encode()).hexdigest()}{ext}"
            output_path = input_path.parent / filename

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(input_path) as img:
            original_mode = img.mode
            original_size = img.size

            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            img = ImageOps.exif_transpose(img)

            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            save_kwargs = {
                'quality': quality,
                'optimize': True
            }

            if format:
                save_format = format.upper()
            else:
                save_format = img.format or 'JPEG'

            if save_format == 'JPEG':
                save_kwargs['progressive'] = True

            img.save(output_path, format=save_format, **save_kwargs)

        logger.info(
            f"图片压缩完成: {input_path} -> {output_path} "
            f"({original_size} -> {img.size}, quality={quality})"
        )

        return str(output_path)

    def add_watermark(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        text: str = "",
        position: str = "bottom-right",
        font_size: int = 30,
        opacity: float = 0.3,
        color: Tuple[int, int, int] = (255, 255, 255),
        angle: int = 0
    ) -> str:
        """
        添加文字水印

        Args:
            input_path: 输入图片路径
            output_path: 输出图片路径（可选）
            text: 水印文字
            position: 水印位置（top-left, top-right, bottom-left, bottom-right, center）
            font_size: 字体大小
            opacity: 透明度 0-1
            color: 颜色 (R, G, B)
            angle: 旋转角度

        Returns:
            输出图片路径
        """
        input_path = Path(input_path)
        
        if not input_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {input_path}")

        if output_path is None:
            ext = input_path.suffix.lower()
            filename = f"{hashlib.md5(str(input_path).encode()).hexdigest()}{ext}"
            output_path = input_path.parent / filename

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(input_path) as img:
            img = img.convert('RGBA')
            img = ImageOps.exif_transpose(img)

            if text:
                watermark = Image.new('RGBA', img.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(watermark)

                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except:
                    font = ImageFont.load_default()

                text_bbox = draw.textbbox((0, 0), text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]

                x, y = self._calculate_position(
                    img.size, (text_width, text_height), position
                )

                color_with_opacity = (*color, int(255 * opacity))
                draw.text((x, y), text, font=font, fill=color_with_opacity)

                if angle != 0:
                    watermark = watermark.rotate(angle, expand=1)
                    watermark = watermark.resize(img.size)

                img = Image.alpha_composite(img, watermark)

            img = img.convert('RGB')
            img.save(output_path, format='JPEG', quality=self.quality)

        logger.info(f"水印添加完成: {input_path} -> {output_path}")
        return str(output_path)

    def add_image_watermark(
        self,
        input_path: Union[str, Path],
        watermark_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        position: str = "bottom-right",
        scale: float = 0.1,
        opacity: float = 0.3
    ) -> str:
        """
        添加图片水印

        Args:
            input_path: 输入图片路径
            watermark_path: 水印图片路径
            output_path: 输出图片路径（可选）
            position: 水印位置
            scale: 水印比例
            opacity: 透明度 0-1

        Returns:
            输出图片路径
        """
        input_path = Path(input_path)
        watermark_path = Path(watermark_path)

        if not input_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {input_path}")
        if not watermark_path.exists():
            raise FileNotFoundError(f"水印图片不存在: {watermark_path}")

        if output_path is None:
            ext = input_path.suffix.lower()
            filename = f"{hashlib.md5(str(input_path).encode()).hexdigest()}{ext}"
            output_path = input_path.parent / filename

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(input_path) as img, Image.open(watermark_path) as watermark:
            img = img.convert('RGBA')
            img = ImageOps.exif_transpose(img)

            watermark = watermark.convert('RGBA')
            
            watermark_size = (
                int(img.size[0] * scale),
                int(watermark.size[1] * (img.size[0] * scale) / watermark.size[0])
            )
            watermark = watermark.resize(watermark_size, Image.Resampling.LANCZOS)

            if opacity < 1:
                alpha = watermark.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
                watermark.putalpha(alpha)

            x, y = self._calculate_position(
                img.size, watermark.size, position
            )

            img.paste(watermark, (x, y), watermark)

            img = img.convert('RGB')
            img.save(output_path, format='JPEG', quality=self.quality)

        logger.info(f"图片水印添加完成: {input_path} -> {output_path}")
        return str(output_path)

    def _calculate_position(
        self,
        img_size: Tuple[int, int],
        item_size: Tuple[int, int],
        position: str
    ) -> Tuple[int, int]:
        """计算位置坐标"""
        img_w, img_h = img_size
        item_w, item_h = item_size
        padding = 10

        positions = {
            'top-left': (padding, padding),
            'top-right': (img_w - item_w - padding, padding),
            'bottom-left': (padding, img_h - item_h - padding),
            'bottom-right': (img_w - item_w - padding, img_h - item_h - padding),
            'center': ((img_w - item_w) // 2, (img_h - item_h) // 2),
        }

        return positions.get(position, positions['bottom-right'])

    def create_thumbnail(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        size: Tuple[int, int] = (200, 200),
        crop: bool = True
    ) -> str:
        """
        创建缩略图

        Args:
            input_path: 输入图片路径
            output_path: 输出图片路径
            size: 缩略图尺寸
            crop: 是否裁剪

        Returns:
            输出图片路径
        """
        input_path = Path(input_path)
        
        if not input_path.exists():
            raise FileNotFoundError(f"图片文件不存在: {input_path}")

        if output_path is None:
            ext = input_path.suffix.lower()
            filename = f"{hashlib.md5(str(input_path).encode()).hexdigest()}_thumb{ext}"
            output_path = input_path.parent / filename

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(input_path) as img:
            img = ImageOps.exif_transpose(img)

            if crop:
                img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
            else:
                img.thumbnail(size, Image.Resampling.LANCZOS)

            img.save(output_path, quality=self.quality)

        logger.info(f"缩略图创建完成: {input_path} -> {output_path}")
        return str(output_path)


try:
    from PIL import ImageEnhance
except ImportError:
    pass
