"""
SaaS 后台管理系统 — 系统管理 API（仪表盘/日志/设置/备份/导出）。
"""
import json

from django.http import HttpResponse
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes as drf_permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from loguru import logger
from django.utils.translation import gettext_lazy as _

from framework.cache.view_cache import drf_cache_view, T_30_SECONDS, T_5_MINUTES, TAG_DASHBOARD, TAG_EXPORT

from ..permissions import (
    SystemDashboardPermission,
    SystemLogsViewPermission,
    SystemSettingsBasicPermission,
    SystemSettingsBackupPermission,
)
from ..models import TenantConfig
from ..services import (
    DashboardService,
    LogService,
    SettingsService,
    BackupService,
)


@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
@drf_cache_view("sys_dashboard", timeout=T_30_SECONDS, tags=[TAG_DASHBOARD])
def system_dashboard_api(request):
    """返回系统仪表盘统计数据"""
    return Response(DashboardService.get_stats())


@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemLogsViewPermission])
def system_logs_api(request):
    """返回日志数据，支持分页和筛选"""
    level = request.query_params.get('level', '').upper()
    search = request.query_params.get('search', '')
    date_from = request.query_params.get('date_from', '')
    date_to = request.query_params.get('date_to', '')
    page = int(request.query_params.get('page', 1))
    page_size = min(int(request.query_params.get('page_size', 50)), 200)

    level_filter = [l for l in level.split(',') if l in LogService.LOG_LEVELS] if level else None

    log_file = LogService.find_latest_log()
    if not log_file:
        return Response({"entries": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 1})

    result = LogService.parse_log(
        log_file, level_filter=level_filter, search=search,
        date_from=date_from, date_to=date_to, page=page, page_size=page_size
    )
    result['log_file'] = str(log_file.name)
    return Response(result)


@api_view(['GET', 'POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemSettingsBasicPermission])
def system_settings_config_api(request):
    """读取/保存系统设置配置项"""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return Response({"detail": _("请先选择租户上下文")}, status=400)

    if request.method == 'GET':
        category = request.query_params.get('category', 'general')
        configs = TenantConfig.objects.filter(tenant=tenant, category=category)
        return Response({
            "configs": {
                c.key: c.value for c in configs
            }
        })

    data = request.data.get('configs', {})
    category = request.data.get('category', 'general')
    updated = []
    for key, value in data.items():
        config, created = TenantConfig.objects.update_or_create(
            tenant=tenant,
            key=key,
            defaults={
                'value': str(value),
                'category': category,
                'description': f'{category} settings',
            }
        )
        updated.append({'key': key, 'value': value, 'created': created})

    logger.info(f"租户 {tenant.name} 更新了 {category} 设置")
    return Response({"updated": updated, "status": "ok"})


@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemSettingsBackupPermission])
def system_backup_api(request):
    """触发系统数据备份（需要 system.settings.backup 权限）"""
    result = BackupService.create_backup()
    if result.get("status") == "error":
        return Response({"detail": result.get("msg", "备份失败")}, status=500)
    return Response(result)


@extend_schema(exclude=True)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemSettingsBackupPermission])
def system_backup_list_api(request):
    """列出备份文件列表"""
    return Response({"backups": BackupService.list_backups()})


@extend_schema(
    summary="导出数据",
    description="按模型、格式、字段导出数据。支持 xlsx/csv/pdf 格式。",
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'model': {'type': 'string', 'description': '模型标识如 saas.Tenant'},
                'format': {'type': 'string', 'description': 'xlsx / csv / pdf'},
                'fields': {'type': 'array', 'items': {'type': 'string'}, 'description': '导出字段（可选，不传使用默认）'},
                'filters': {'type': 'object', 'description': '额外筛选条件（可选）'},
                'async': {'type': 'boolean', 'description': '是否异步导出（>1万条建议开启）'},
            },
            'required': ['model', 'format'],
        }
    },
    tags=['数据导出'],
    responses={200: {'content': {'application/octet-stream': {}}}},
)
@api_view(['POST'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
def export_data(request):
    """导出数据为 Excel / CSV / PDF。"""
    from framework.files.export import get_exporter, ExportConfig, EXPORTABLE_MODELS

    model_label = request.data.get('model', '')
    fmt = request.data.get('format', 'xlsx')
    fields = request.data.get('fields')
    filters = request.data.get('filters', {})
    filename = request.data.get('filename')
    use_async = request.data.get('async', False)

    if model_label not in EXPORTABLE_MODELS:
        return Response({
            "detail": f'不支持的导出模型: {model_label}',
            "available": list(EXPORTABLE_MODELS.keys()),
        }, status=400)

    base = EXPORTABLE_MODELS[model_label]

    try:
        config = ExportConfig(
            model_label=model_label,
            fields=fields or base.fields,
            headers=base.headers,
            filename=filename or base.filename,
            filters={**base.filters, **filters},
            related_select=base.related_select,
            related_prefetch=base.related_prefetch,
            order_by=base.order_by,
        )
        exporter = get_exporter(config, fmt)
    except ValueError as e:
        return Response({"detail": str(e)}, status=400)

    qs = exporter.get_queryset()

    if use_async or qs.count() > 10000:
        from ..tasks import async_export_data
        task = async_export_data.delay(
            model_label=model_label,
            fmt=fmt,
            fields=fields,
            filters=filters,
            filename=filename,
        )
        return Response({
            "status": "processing",
            "task_id": task.id,
            "msg": "数据量较大，已转为后台异步导出，完成后可下载",
        })

    data = exporter.export(qs)
    response = HttpResponse(data, content_type=exporter.content_type)
    response['Content-Disposition'] = (
        f'attachment; filename="{config.filename}.{exporter.extension}"'
    )
    return response


@extend_schema(
    summary="获取可导出模型列表",
    description="返回所有可导出模型的标识和可用字段",
    tags=['数据导出'],
)
@api_view(['GET'])
@drf_permission_classes([permissions.IsAuthenticated, SystemDashboardPermission])
@drf_cache_view("export_models", timeout=T_5_MINUTES, tags=[TAG_EXPORT])
def export_models(request):
    """列出所有可导出模型及其字段"""
    from framework.files.export import EXPORTABLE_MODELS
    models = {}
    for label, cfg in EXPORTABLE_MODELS.items():
        models[label] = {
            'name': cfg.filename,
            'fields': cfg.fields,
            'headers': cfg.headers,
            'supported_formats': ['xlsx', 'csv', 'pdf'],
        }
    return Response({"models": models})
