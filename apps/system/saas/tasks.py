"""
SaaS 异步任务（Celery）
"""
import os
import tempfile
from celery import shared_task
from loguru import logger

from framework.files.export import get_exporter, ExportConfig, EXPORTABLE_MODELS


@shared_task(bind=True, max_retries=3)
def async_export_data(self, model_label: str, fmt: str = 'xlsx',
                       fields: list = None, filters: dict = None,
                       filename: str = None):
    """
    异步导出数据到文件，返回文件路径
    用于大数据量导出，避免请求超时

    返回: {'filepath': str, 'filename': str, 'size': int, 'content_type': str}
    """
    try:
        # 获取基础配置
        base_config = EXPORTABLE_MODELS.get(model_label)
        if not base_config:
            raise ValueError(f"模型 {model_label} 未注册导出配置")

        # 合并用户指定的字段和筛选
        config = ExportConfig(
            model_label=model_label,
            fields=fields or base_config.fields,
            headers=base_config.headers,
            filename=filename or base_config.filename,
            filters=filters or base_config.filters,
            related_select=base_config.related_select,
            related_prefetch=base_config.related_prefetch,
            order_by=base_config.order_by,
        )

        # 创建导出器
        exporter = get_exporter(config, fmt)

        # 导出到临时文件
        export_dir = os.path.join(tempfile.gettempdir(), 'django_exports')
        filepath = exporter.export_to_file(directory=export_dir)

        file_size = os.path.getsize(filepath)

        logger.info(f'异步导出完成: {filepath} ({file_size} bytes)')

        return {
            'filepath': filepath,
            'filename': os.path.basename(filepath),
            'size': file_size,
            'content_type': exporter.content_type,
        }

    except Exception as e:
        logger.error(f'异步导出失败: {e}')
        self.retry(exc=e, countdown=60)
