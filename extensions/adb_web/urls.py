from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AdbDeviceViewSet, AdbMetaViewSet

router = DefaultRouter()
router.register(r"devices", AdbDeviceViewSet, basename="adb-devices")
router.register(r"meta", AdbMetaViewSet, basename="adb-meta")

urlpatterns = router.urls
