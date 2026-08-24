"""
入站 Webhook 接收视图（验签 + 派发）。

接入（可选）：
    # djangoProjectTest/urls.py
    path('webhooks/', include('framework.webhooks.urls'))

POST /webhooks/<source>/   请求体为原始字节；头 ``X-Hub-Signature-256`` 携带 HMAC。
各来源密钥通过 ``configure_source(source, secret)`` 在启动时注册（或从 settings 读取）。
"""
import json

from django.http import JsonResponse
from django.views import View

from framework.webhooks.dispatcher import dispatch
from framework.webhooks.signature import verify_signature

# source -> 签名密钥（运行时注册）
_SECRET_LOOKUP: dict = {}


def configure_source(source: str, secret: str) -> None:
    _SECRET_LOOKUP[source] = secret


class WebhookView(View):
    def post(self, request, source: str):
        secret = _SECRET_LOOKUP.get(source)
        sig = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
        raw = request.body
        if secret and not verify_signature(secret, raw, sig):
            return JsonResponse({"detail": "invalid signature"}, status=401)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"detail": "invalid json"}, status=400)
        event_type = payload.get("type") or source
        result = dispatch(event_type, payload)
        return JsonResponse(
            {"received": True, "dispatched": event_type, "handled": result is not None},
            status=200,
        )
