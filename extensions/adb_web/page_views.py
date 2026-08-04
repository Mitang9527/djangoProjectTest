from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods


@login_required
@require_http_methods(["GET"])
def dashboard(request):
    """ADB 工具 Web 管理页"""
    from system.saas.permissions import _is_super_admin
    return render(request, "adb_web/dashboard.html", {
        "title": "终端 设备管理",
        "is_super_admin": _is_super_admin(request.user),
    })
