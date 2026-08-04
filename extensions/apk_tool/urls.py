from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views as api_views

router = DefaultRouter()
router.register(r'tasks', api_views.BuildTaskViewSet, basename='build-task')

# 注意：此文件只包含 API 路由，页面路由已移到 saas/urls.py
urlpatterns = [
    path('', include(router.urls)),
]
