"""
Sentry 错误追踪集成
- 自动捕获未处理异常
- 过滤敏感信息
- 关联用户上下文
- 标记 Release 版本
"""
import os

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from django.conf import settings


def before_send(event, hint):
    """
    发送前过滤敏感信息
    """
    # 过滤 HTTP 请求中的敏感字段
    if "request" in event:
        request_data = event["request"]
        # 过滤 headers 中的认证信息
        if "headers" in request_data:
            sensitive_headers = ["authorization", "cookie", "x-api-key", "x-signature"]
            for header in sensitive_headers:
                if header in request_data["headers"]:
                    request_data["headers"][header] = "[REDACTED]"
        # 过滤 POST/GET 数据中的密码字段
        for field in ["data", "query_string"]:
            if field in request_data and isinstance(request_data[field], dict):
                sensitive_fields = [
                    "password", "old_password", "new_password",
                    "password1", "password2", "secret", "token",
                    "api_key", "stamp_key", "secret_key",
                ]
                for key in list(request_data[field].keys()):
                    if any(s in key.lower() for s in sensitive_fields):
                        request_data[field][key] = "[REDACTED]"

    return event


def init_sentry():
    """
    初始化 Sentry SDK
    从环境变量 SENTRY_DSN 读取 DSN，未配置则跳过
    """
    sentry_dsn = os.environ.get("SENTRY_DSN", "")

    if not sentry_dsn:
        return

    # 获取环境信息
    environment = os.environ.get("ENV", "DEV").lower()
    release = os.environ.get("RELEASE_VERSION", None)

    try:
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=environment,
            release=release,
            # 采样率
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            # 发送前过滤敏感信息
            before_send=before_send,
            # 集成
            integrations=[
                DjangoIntegration(
                    transaction_style="url",
                    middleware_spans=True,
                    signals_spans=False,
                ),
                CeleryIntegration(),
                RedisIntegration(),
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR,
                ),
            ],
            # 过滤敏感用户信息
            send_default_pii=False,
            # 请求体大小限制
            max_request_body_size="medium",
        )
    except Exception as exc:  # pragma: no cover - 初始化失败（如本地证书库异常）不应阻断服务启动
        logging.getLogger("sentry").warning("Sentry 初始化失败，已跳过: %s", exc)
        return

    # #10 — 通知 loguru Sentry 已就绪, 后续 ERROR+ 日志自动转发
    from framework.log_utils.loguru_control import mark_sentry_enabled
    mark_sentry_enabled()


# 延迟导入 logging，避免循环引用
import logging  # noqa: E402
