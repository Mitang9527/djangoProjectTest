"""
framework.webhooks — 入站 Webhook 框架。

区别于 framework.notice_utils 里的「出站」webhook（向企业微信/飞书发消息），
本模块处理「入站」回调：HMAC 验签 + 事件派发 + 接收视图。
"""
from framework.webhooks.dispatcher import dispatch, register
from framework.webhooks.signature import sign_body, verify_signature
from framework.webhooks.views import WebhookView, configure_source

__all__ = ["WebhookView", "register", "dispatch", "verify_signature", "sign_body", "configure_source"]
