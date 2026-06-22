from rest_framework.routers import DefaultRouter
from .views import SoulViewSet

router = DefaultRouter()
# 使用 r'' 注册，使接口直接挂载在 api/soul/ 下，避免 api/soul/soul/
router.register(r'', SoulViewSet, basename='soul')

urlpatterns = router.urls
