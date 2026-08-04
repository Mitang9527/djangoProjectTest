import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from loguru import logger

from .models import BuildTask
from .services.config_service import list_terminal_configs


@login_required
def apk_dashboard(request):
    """APK 工具仪表盘（在 SaaS 后台下）"""
    logger.info(f"[APK Page] 访问仪表盘 — user={request.user.username}")
    recent_tasks = BuildTask.objects.filter(creator=request.user).order_by('-created_at')[:10]
    total_tasks = BuildTask.objects.filter(creator=request.user).count()
    completed_tasks = BuildTask.objects.filter(creator=request.user, status='completed').count()

    context = {
        'recent_tasks': recent_tasks,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'active_tab': 'apk_tool',
        'title': 'APK 定制工具',
        'is_super_admin': request.user.is_superuser,
    }
    return render(request, 'apk_tool/dashboard.html', context)


@login_required
def apk_build_page(request):
    """APK 构建页面"""
    logger.info(f"[APK Page] 访问构建页面 — user={request.user.username}")
    terminal_configs = list_terminal_configs()
    # 序列化为 JSON 字符串，供前端 JS 直接使用
    terminal_configs_json = json.dumps(terminal_configs, ensure_ascii=False)
    task_id = request.GET.get('task_id')

    current_task = None
    if task_id:
        try:
            current_task = BuildTask.objects.get(id=task_id)
            logger.debug(f"[APK Page] 加载已有任务 — task_id={task_id}")
        except BuildTask.DoesNotExist:
            logger.warning(f"[APK Page] 任务不存在 — task_id={task_id}")

    context = {
        'terminal_configs_json': terminal_configs_json,
        'current_task': current_task,
        'active_tab': 'apk_tool',
        'title': 'APK 构建',
        'is_super_admin': request.user.is_superuser,
    }
    return render(request, 'apk_tool/build.html', context)


@login_required
def apk_task_detail(request, task_id):
    """任务详情页面"""
    logger.info(f"[APK Page] 访问任务详情 — task_id={task_id}, user={request.user.username}")
    task = get_object_or_404(BuildTask, id=task_id)
    context = {
        'task': task,
        'active_tab': 'apk_tool',
        'title': '任务详情',
        'is_super_admin': request.user.is_superuser,
    }
    return render(request, 'apk_tool/task_detail.html', context)


@login_required
def apk_terminal_page(request):
    """终端配置管理页面"""
    logger.info(f"[APK Page] 访问终端配置 — user={request.user.username}")
    configs = list_terminal_configs()
    configs_json = json.dumps(configs, ensure_ascii=False)
    context = {
        'configs': configs,
        'configs_json': configs_json,
        'total': len(configs),
        'active_tab': 'apk_tool',
        'title': '终端配置',
        'is_super_admin': request.user.is_superuser,
    }
    return render(request, 'apk_tool/terminal.html', context)
