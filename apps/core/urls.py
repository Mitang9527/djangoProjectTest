from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import IndexView, ApiConfigView, AuditLogViewSet, WebSocketDemoView, SystemStatusView

app_name = 'core'

router = DefaultRouter()
router.register('audit-log', AuditLogViewSet, basename='audit-log')

urlpatterns = [
    path('', IndexView.as_view(), name='index'),
    path('system-status/', SystemStatusView.as_view(), name='system-status'),
    path('websocket-demo/', WebSocketDemoView.as_view(), name='websocket-demo'),
    path('api/config/', ApiConfigView.as_view(), name='api-config'),
    path('api/', include(router.urls)),
]
