"""文件清理 Celery 任务。

提供定时清理临时目录/过期文件的 ``clean_temp_files`` 任务，支持 dry-run 预览，
由 beat 调度或手动触发。
"""
import os
import time
import tempfile
from pathlib import Path
from datetime import timedelta, datetime
from django.conf import settings
from django.utils import timezone
from celery import shared_task
from loguru import logger


@shared_task(name="files.clean_temp_files")
def clean_temp_files(
    temp_dirs: list = None,
    max_age_hours: int = 24,
    dry_run: bool = False
) -> dict:
    """
    清理临时文件

    Args:
        temp_dirs: 要清理的临时目录列表
        max_age_hours: 文件最大保留时间（小时）
        dry_run: 是否为模拟运行（不实际删除）

    Returns:
        清理结果统计
    """
    if temp_dirs is None:
        temp_dirs = getattr(settings, 'FILE_UPLOAD_TEMP_DIRS', [])
        if not temp_dirs:
            temp_dirs = [
                os.path.join(settings.MEDIA_ROOT, 'temp'),
                # 不要用硬编码 '/tmp'：Windows 下不存在，且应尊重 TMPDIR。
                tempfile.gettempdir(),
            ]

    stats = {
        'directories_scanned': 0,
        'files_deleted': 0,
        'bytes_freed': 0,
        'errors': []
    }

    cutoff_time = time.time() - (max_age_hours * 3600)

    for temp_dir in temp_dirs:
        temp_path = Path(temp_dir)
        
        if not temp_path.exists():
            continue
        
        if not temp_path.is_dir():
            continue

        stats['directories_scanned'] += 1
        logger.info(f"扫描目录: {temp_dir}")

        try:
            for root, dirs, files in os.walk(temp_path, topdown=False):
                for file in files:
                    file_path = Path(root) / file
                    
                    try:
                        file_mtime = file_path.stat().st_mtime
                        
                        if file_mtime < cutoff_time:
                            file_size = file_path.stat().st_size
                            
                            if not dry_run:
                                file_path.unlink()
                                logger.info(f"已删除: {file_path} ({file_size / 1024:.2f} KB)")
                            else:
                                logger.info(f"模拟删除: {file_path}")
                            
                            stats['files_deleted'] += 1
                            stats['bytes_freed'] += file_size
                    
                    except Exception as e:
                        error_msg = f"处理文件失败 {file_path}: {str(e)}"
                        stats['errors'].append(error_msg)
                        logger.error(error_msg)

                for dir_name in dirs:
                    dir_path = Path(root) / dir_name
                    try:
                        if not any(dir_path.iterdir()):
                            if not dry_run:
                                dir_path.rmdir()
                                logger.info(f"已删除空目录: {dir_path}")
                    except Exception as e:
                        error_msg = f"删除目录失败 {dir_path}: {str(e)}"
                        stats['errors'].append(error_msg)
                        logger.error(error_msg)

        except Exception as e:
            error_msg = f"扫描目录失败 {temp_dir}: {str(e)}"
            stats['errors'].append(error_msg)
            logger.error(error_msg)

    logger.info(
        f"临时文件清理完成: 删除 {stats['files_deleted']} 个文件, "
        f"释放 {stats['bytes_freed'] / 1024 / 1024:.2f} MB"
    )

    return stats


@shared_task(name="files.clean_old_uploads")
def clean_old_uploads(
    upload_dirs: list = None,
    max_age_days: int = 30,
    dry_run: bool = False
) -> dict:
    """
    清理旧的上传文件

    Args:
        upload_dirs: 上传目录列表
        max_age_days: 文件最大保留天数
        dry_run: 是否为模拟运行

    Returns:
        清理结果统计
    """
    if upload_dirs is None:
        upload_dirs = getattr(settings, 'FILE_UPLOAD_DIRS', [])
        if not upload_dirs:
            upload_dirs = [settings.MEDIA_ROOT]

    stats = {
        'directories_scanned': 0,
        'files_deleted': 0,
        'bytes_freed': 0,
        'errors': []
    }

    cutoff_date = timezone.now() - timedelta(days=max_age_days)

    for upload_dir in upload_dirs:
        upload_path = Path(upload_dir)
        
        if not upload_path.exists():
            continue

        stats['directories_scanned'] += 1
        logger.info(f"扫描上传目录: {upload_dir}")

        try:
            for item in upload_path.rglob('*'):
                if item.is_file():
                    try:
                        file_mtime = datetime.fromtimestamp(
                            item.stat().st_mtime, tz=timezone.get_current_timezone()
                        )
                        
                        if file_mtime < cutoff_date:
                            file_size = item.stat().st_size
                            
                            if not dry_run:
                                item.unlink()
                                logger.info(f"已删除旧文件: {item}")
                            
                            stats['files_deleted'] += 1
                            stats['bytes_freed'] += file_size
                    
                    except Exception as e:
                        error_msg = f"处理文件失败 {item}: {str(e)}"
                        stats['errors'].append(error_msg)
                        logger.error(error_msg)

        except Exception as e:
            error_msg = f"扫描目录失败 {upload_dir}: {str(e)}"
            stats['errors'].append(error_msg)
            logger.error(error_msg)

    logger.info(
        f"旧文件清理完成: 删除 {stats['files_deleted']} 个文件, "
        f"释放 {stats['bytes_freed'] / 1024 / 1024:.2f} MB"
    )

    return stats
