import logging
from .masking import DataMasker


class MaskingFilter(logging.Filter):
    """日志脱敏过滤器"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if hasattr(record, 'msg') and isinstance(record.msg, str):
                record.msg = DataMasker.mask_all(record.msg)

            if hasattr(record, 'args'):
                if isinstance(record.args, dict):
                    record.args = DataMasker.mask_dict(record.args)
                elif isinstance(record.args, (list, tuple)):
                    record.args = tuple(
                        DataMasker.mask_all(str(arg)) if isinstance(arg, str) else arg
                        for arg in record.args
                    )

        except Exception as e:
            pass

        return True


def setup_loguru_masking():
    """配置 Loguru 脱敏"""
    from loguru import logger
    from .masking import mask_data

    def patcher(record):
        if record["message"]:
            record["message"] = mask_data(record["message"])
        if record["extra"]:
            record["extra"] = mask_data(record["extra"])

    logger.configure(patcher=patcher)
