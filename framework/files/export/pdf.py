"""
PDF (.pdf) 导出器
基于 reportlab，支持中文字体、自动分页、表头重复
"""
from io import BytesIO

from django.db.models import QuerySet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .base import BaseExporter


class PDFExporter(BaseExporter):
    """PDF 格式导出器"""
    content_type = 'application/pdf'
    extension = 'pdf'

    # 页面配置
    PAGE_SIZE = landscape(A4)
    MARGIN = 15 * mm

    def __init__(self, config):
        super().__init__(config)
        self._font_registered = False

    def _register_font(self):
        """注册中文字体（尝试多个路径）"""
        if self._font_registered:
            return
        font_paths = [
            'C:/Windows/Fonts/msyh.ttc',       # 微软雅黑 Windows
            'C:/Windows/Fonts/simsun.ttc',      # 宋体
            'C:/Windows/Fonts/simhei.ttf',      # 黑体
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',  # Linux
            '/System/Library/Fonts/PingFang.ttc',  # macOS
        ]
        for path in font_paths:
            try:
                pdfmetrics.registerFont(TTFont('ChineseFont', path))
                self._font_registered = True
                return
            except Exception:
                continue
        # 兜底：使用 reportlab 内置字体（不支持中文）
        self._font_registered = True

    def export(self, queryset: QuerySet) -> bytes:
        self._register_font()

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=self.PAGE_SIZE,
            leftMargin=self.MARGIN,
            rightMargin=self.MARGIN,
            topMargin=self.MARGIN,
            bottomMargin=self.MARGIN,
            title=self.config.filename,
        )

        elements = []

        # 标题
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'ExportTitle',
            parent=styles['Title'],
            fontName='ChineseFont',
            fontSize=16,
            spaceAfter=10 * mm,
        )
        elements.append(Paragraph(self.config.filename, title_style))

        count = queryset.count()
        summary_style = ParagraphStyle(
            'Summary',
            parent=styles['Normal'],
            fontName='ChineseFont',
            fontSize=9,
            textColor=colors.HexColor('#6B7280'),
            spaceAfter=5 * mm,
        )
        elements.append(Paragraph(f'共 {count} 条记录', summary_style))

        headers = self.config.get_headers()
        col_count = len(headers)

        # 表头行
        header_row = [Paragraph(h, ParagraphStyle(
            'HeaderCell',
            fontName='ChineseFont',
            fontSize=9,
            leading=12,
            textColor=colors.white,
            alignment=1,  # center
        )) for h in headers]

        table_data = [header_row]

        # 数据行
        cell_style = ParagraphStyle(
            'DataCell',
            fontName='ChineseFont',
            fontSize=8,
            leading=11,
        )
        for obj in queryset.iterator(chunk_size=500):
            row = [Paragraph(self._resolve_value(obj, f), cell_style)
                   for f in self.config.fields]
            table_data.append(row)

        # 计算列宽
        available_width = self.PAGE_SIZE[0] - 2 * self.MARGIN
        col_width = available_width / col_count

        table = Table(table_data, colWidths=[col_width] * col_count, repeatRows=1)
        table.setStyle(TableStyle([
            # 表头
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F2937')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'ChineseFont'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),

            # 数据行
            ('FONTNAME', (0, 1), (-1, -1), 'ChineseFont'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),

            # 网格线
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#374151')),

            # 交替行底色
            *[('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F9FAFB'))
              for i in range(2, len(table_data) + 1, 2)],
        ]))

        elements.append(table)
        doc.build(elements)
        return buf.getvalue()
