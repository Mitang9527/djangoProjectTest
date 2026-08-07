"""
CSV (.csv) 导出器
UTF-8 BOM 编码，确保 Excel 直接打开不乱码
"""
import csv
from io import StringIO

from django.db.models import QuerySet

from .base import BaseExporter


class CSVExporter(BaseExporter):
    """CSV 格式导出器"""
    content_type = 'text/csv; charset=utf-8-sig'
    extension = 'csv'

    def export(self, queryset: QuerySet) -> bytes:
        output = StringIO()
        # BOM + Excel 方言
        output.write('\ufeff')

        writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC)

        # 表头
        writer.writerow(self.config.get_headers())

        # 数据行
        for obj in queryset.iterator(chunk_size=1000):
            writer.writerow([self._resolve_value(obj, f) for f in self.config.fields])

        return output.getvalue().encode('utf-8-sig')
