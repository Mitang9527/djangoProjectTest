from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AdbDeviceViewSet, AdbMetaViewSet
from .page_views import dashboard

router = DefaultRouter()
router.register(r"devices", AdbDeviceViewSet, basename="adb-devices")
router.register(r"meta", AdbMetaViewSet, basename="adb-meta")

urlpatterns = [
    path("dashboard/", dashboard, name="adb-dashboard"),
] + router.urls
