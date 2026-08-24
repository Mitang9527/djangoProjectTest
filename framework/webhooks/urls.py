"""入站 Webhook 路由。在 ROOT_URLCONF 中 include 即可启用。"""
from django.urls import path

from framework.webhooks.views import WebhookView

app_name = "webhooks"
urlpatterns = [
    path("<str:source>/", WebhookView.as_view(), name="receive"),
]
