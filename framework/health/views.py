"""
健康检查视图。

- HealthView   : /healthz  存活探针，永远 200。
- ReadinessView: /readyz   就绪探针，依赖检查失败返回 503。
"""
from django.http import JsonResponse
from django.views import View

from . import checks
from ..core.env_loader import get_env_type


class HealthView(View):
    """存活探针：进程在即返回 200，不触碰任何外部依赖。"""

    def get(self, request, *args, **kwargs):
        return JsonResponse(
            {"status": "ok", "probe": "liveness"},
            status=200,
        )


class ReadinessView(View):
    """就绪探针：聚合 DB / Cache / Broker 检查结果，任一 FAIL 即 503。"""

    def get(self, request, *args, **kwargs):
        results = checks.collect_readiness()
        failed = [r for r in results if (not r.ok) and (not r.skipped)]
        payload = {
            "status": "ok" if not failed else "degraded",
            "probe": "readiness",
            "checks": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "skipped": r.skipped,
                    "detail": r.detail,
                    "duration_ms": round(r.duration_ms, 1),
                }
                for r in results
            ],
        }
        return JsonResponse(payload, status=503 if failed else 200)
