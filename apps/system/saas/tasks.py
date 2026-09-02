"""
SaaS 异步任务（Celery）
"""
import os
import tempfile
from celery import shared_task
from loguru import logger

from framework.files.export import get_exporter, ExportConfig, EXPORTABLE_MODELS
from framework.reliability import retry


@retry(
    max_attempts=3,
    backoff="exponential",
    jitter=True,
    retry_on=(Exception,),
    initial_delay=60,
    max_delay=120,
)
def _run_export(model_label: str, fmt: str, fields, filters, filename):
    """带重试的数据导出（失败退避后重试，避免大导出因瞬时故障丢失）。"""
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


@shared_task(name="saas.async_export_data")
def async_export_data(model_label: str, fmt: str = 'xlsx',
                      fields: list = None, filters: dict = None,
                      filename: str = None):
    """
    异步导出数据到文件，返回文件路径
    用于大数据量导出，避免请求超时

    返回: {'filepath': str, 'filename': str, 'size': int, 'content_type': str}
    """
    try:
        return _run_export(model_label, fmt, fields, filters, filename)
    except Exception as e:
        logger.error(f'异步导出失败: {e}')
        raise
