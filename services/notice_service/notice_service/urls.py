from django.urls import path

from notice_app.views import HealthView, NotifyView

urlpatterns = [
    path("api/health/", HealthView.as_view()),
    path("api/notice/notify/", NotifyView.as_view()),
]
