"""
导出引擎基类
定义导出配置、通用 queryset 解析逻辑、格式路由
"""
import tempfile
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Type

from django.apps import apps
from django.db.models import QuerySet


@dataclass
class ExportConfig:
    """导出配置 — 描述一次导出请求的参数"""
    model_label: str                          # e.g. 'saas.Tenant'
    fields: list[str]                         # 导出字段
    headers: dict[str, str] = field(default_factory=dict)  # 字段 → 中文表头
    filename: str = 'export'                  # 不含扩展名
    filters: dict = field(default_factory=dict)           # queryset filter(k=v)
    related_select: list[str] = field(default_factory=list)  # select_related
    related_prefetch: list[str] = field(default_factory=list)  # prefetch_related
    order_by: list[str] = field(default_factory=list)

    @property
    def model_class(self):
        return apps.get_model(self.model_label)

    def get_headers(self) -> list[str]:
        """返回有序的表头列表"""
        return [self.headers.get(f, f) for f in self.fields]


class BaseExporter(ABC):
    """导出器基类"""
    content_type: str = 'application/octet-stream'
    extension: str = 'dat'

    def __init__(self, config: ExportConfig):
        self.config = config

    def get_queryset(self) -> QuerySet:
        """构建导出用的 queryset"""
        model = self.config.model_class
        qs = model.objects.filter(**self.config.filters)
        if self.config.related_select:
            qs = qs.select_related(*self.config.related_select)
        if self.config.related_prefetch:
            qs = qs.prefetch_related(*self.config.related_prefetch)
        if self.config.order_by:
            qs = qs.order_by(*self.config.order_by)
        return qs

    def _resolve_value(self, obj, field_name: str) -> str:
        """解析对象的字段值（支持跨关系，如 owner__username）"""
        parts = field_name.split('__')
        val = obj
        for part in parts:
            val = getattr(val, part, None)
            if val is None:
                return ''
        if isinstance(val, datetime):
            return val.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(val, bool):
            return '是' if val else '否'
        return str(val)

    def _get_rows(self, queryset: QuerySet) -> list[list[str]]:
        """从 queryset 提取行数据"""
        rows = []
        for obj in queryset.iterator(chunk_size=500):
            row = [self._resolve_value(obj, f) for f in self.config.fields]
            rows.append(row)
        return rows

    @abstractmethod
    def export(self, queryset: QuerySet) -> bytes:
        """导出为字节流"""
        ...

    def export_to_file(self, directory: Optional[str] = None) -> str:
        """
        导出到文件，返回文件路径
        如果未指定目录，使用系统临时目录
        """
        target_dir = directory or tempfile.gettempdir()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{self.config.filename}_{timestamp}.{self.extension}"
        filepath = os.path.join(target_dir, filename)
        os.makedirs(target_dir, exist_ok=True)

        qs = self.get_queryset()
        data = self.export(qs)
        with open(filepath, 'wb') as f:
            f.write(data)
        return filepath


# ============================================================
# 格式 → 导出器路由
# ============================================================
def get_exporter(config: ExportConfig, fmt: str) -> BaseExporter:
    """根据格式字符串返回对应的导出器实例"""
    from .excel import ExcelExporter
    from .csv import CSVExporter
    from .pdf import PDFExporter

    exporters = {
        'xlsx': ExcelExporter,
        'csv': CSVExporter,
        'pdf': PDFExporter,
    }
    exporter_cls = exporters.get(fmt.lower())
    if not exporter_cls:
        raise ValueError(f"不支持的导出格式: {fmt}，可选: {list(exporters.keys())}")
    return exporter_cls(config)


# ============================================================
# 模型导出注册表 — 定义哪些模型可导出及默认字段
# ============================================================
EXPORTABLE_MODELS: dict[str, ExportConfig] = {
    'users.User': ExportConfig(
        model_label='users.User',
        fields=['username', 'email', 'nickname', 'phone', 'role', 'is_active', 'date_joined'],
        headers={
            'username': '用户名', 'email': '邮箱', 'nickname': '昵称',
            'phone': '手机号', 'role': '系统角色', 'is_active': '启用',
            'date_joined': '注册时间',
        },
        filename='用户列表',
        related_select=['role'],
        order_by=['-date_joined'],
    ),
    'saas.Tenant': ExportConfig(
        model_label='saas.Tenant',
        fields=['name', 'slug', 'code', 'status', 'plan__name', 'created_by__username', 'created_at'],
        headers={
            'name': '租户名称', 'slug': '标识', 'code': '编码',
            'status': '状态', 'plan__name': '套餐', 'created_by__username': '创建者',
            'created_at': '创建时间',
        },
        filename='租户列表',
        related_select=['plan', 'created_by'],
        order_by=['-created_at'],
    ),
    'saas.TenantMember': ExportConfig(
        model_label='saas.TenantMember',
        fields=['tenant__name', 'user__username', 'role__name', 'is_active', 'joined_at'],
        headers={
            'tenant__name': '租户', 'user__username': '用户', 'role__name': '角色',
            'is_active': '启用', 'joined_at': '加入时间',
        },
        filename='成员列表',
        related_select=['tenant', 'user', 'role'],
        order_by=['-joined_at'],
    ),
    'saas.Order': ExportConfig(
        model_label='saas.Order',
        fields=['order_no', 'tenant__name', 'plan__name', 'amount', 'currency',
                'status', 'payment_method', 'created_at'],
        headers={
            'order_no': '订单号', 'tenant__name': '租户', 'plan__name': '套餐',
            'amount': '金额', 'currency': '币种', 'status': '状态',
            'payment_method': '支付方式', 'created_at': '创建时间',
        },
        filename='订单列表',
        related_select=['tenant', 'plan'],
        order_by=['-created_at'],
    ),
    'saas.Invoice': ExportConfig(
        model_label='saas.Invoice',
        fields=['invoice_no', 'tenant__name', 'order__order_no', 'amount', 'currency',
                'status', 'due_date', 'created_at'],
        headers={
            'invoice_no': '发票号', 'tenant__name': '租户', 'order__order_no': '关联订单',
            'amount': '金额', 'currency': '币种', 'status': '状态',
            'due_date': '到期日', 'created_at': '创建时间',
        },
        filename='发票列表',
        related_select=['tenant', 'order'],
        order_by=['-created_at'],
    ),
    'saas.Permission': ExportConfig(
        model_label='saas.Permission',
        fields=['slug', 'module', 'name', 'description', 'is_active'],
        headers={
            'slug': '权限标识', 'module': '模块', 'name': '名称',
            'description': '描述', 'is_active': '启用',
        },
        filename='权限列表',
        order_by=['module', 'slug'],
    ),
    'saas.Role': ExportConfig(
        model_label='saas.Role',
        fields=['name', 'slug', 'tenant__name', 'is_system', 'is_active', 'created_at'],
        headers={
            'name': '角色名', 'slug': '标识', 'tenant__name': '所属租户',
            'is_system': '系统角色', 'is_active': '启用', 'created_at': '创建时间',
        },
        filename='角色列表',
        related_select=['tenant'],
        order_by=['-is_system', 'name'],
    ),
}
