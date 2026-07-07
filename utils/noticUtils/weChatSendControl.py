"""
企业微信 Webhook 消息发送
=========================

支持文本 / Markdown / 文件 等消息类型，提供异常体系、连接复用、可配置超时与重试。

Examples
--------
>>> sender = WeChatSend()
>>> sender.send_text("Hello, World!", at_all=True)
>>> sender.send_markdown("## 通知\\n**重要**")
>>> sender.send_wechat_notification(metrics)
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse, parse_qs

import requests
from django.conf import settings
from loguru import logger


# ============================================================================
# 异常体系
# ============================================================================

class WeChatSendError(Exception):
    """企业微信发送失败基异常"""


class WebhookNotConfiguredError(WeChatSendError):
    """settings.WECHAT_WEBHOOK 未配置"""


# ============================================================================
# 发送器
# ============================================================================

class WeChatSend:
    """
    企业微信 Webhook 消息发送器。

    Parameters
    ----------
    metrics : Any, optional
        测试报告指标对象（用于 send_wechat_notification 模板）。
    webhook : str, optional
        形如 ``https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx``。
        留空则从 ``settings.WECHAT_WEBHOOK`` 读取。
    timeout : float
        HTTP 请求超时（秒），默认 10。
    max_retries : int
        网络错误重试次数（不含 200 OK 但 errcode != 0 的情况），默认 0。
    session : requests.Session, optional
        自定义连接池，便于复用 TCP 连接。
    """

    DEFAULT_TIMEOUT = 10
    _HEADERS = {"Content-Type": "application/json"}  # 类级别常量

    def __init__(
        self,
        metrics: Any = None,
        webhook: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.metrics = metrics
        self.webhook = webhook or getattr(settings, "WECHAT_WEBHOOK", None)
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def send_text(
        self,
        content: str,
        mentioned_mobile_list: Optional[Iterable[str]] = None,
        mentioned_list: Optional[Iterable[str]] = None,
        at_all: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        发送文本消息。

        Parameters
        ----------
        content : str
            消息正文。
        mentioned_mobile_list : iterable of str, optional
            @ 成员的手机号列表。
        mentioned_list : iterable of str, optional
            @ 成员的 userid 列表。
        at_all : bool
            是否 @ 所有人（设置为 True 时 mentioned_list 会被覆盖为 ["@all"]）。
        """
        if at_all:
            mentioned_list = ["@all"]
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": list(mentioned_list or []),
                "mentioned_mobile_list": list(mentioned_mobile_list or []),
            },
        }
        return self._post(payload)

    def send_markdown(self, content: str) -> Optional[Dict[str, Any]]:
        """发送 Markdown 消息（企业微信侧渲染）。"""
        return self._post({"msgtype": "markdown", "markdown": {"content": content}})

    def send_file_msg(self, file: str) -> Optional[Dict[str, Any]]:
        """
        发送文件类型的消息（先上传到临时媒体库，再发送 media_id）。

        Parameters
        ----------
        file : str
            本地文件路径。
        """
        media_id = self._upload_file(file)
        return self._post({"msgtype": "file", "file": {"media_id": media_id}})

    def send_wechat_notification(self, metrics: Any = None) -> Optional[Dict[str, Any]]:
        """发送测试报告通知。``metrics`` 需提供 pass_rate/total/passed/failed/broken/skipped/time 属性。"""
        m = metrics or self.metrics
        if m is None:
            logger.warning("WeChatSend.send_wechat_notification 收到空 metrics，已跳过")
            return None

        project_name = getattr(settings, "PROJECT_NAME", "DjangoProject")
        tester_name = getattr(settings, "TESTER_NAME", "Admin")
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        text = (
            f"【{project_name}自动化通知】\n"
            f"> 测试环境：<font color=\"info\">TEST</font>\n"
            f"> 测试负责人：@{tester_name}\n"
            f">\n"
            f"> **执行结果**\n"
            f"> 成功率：<font color=\"info\">{m.pass_rate}%</font>\n"
            f"> 用例总数：<font color=\"info\">{m.total}</font>\n"
            f"> 成功用例：<font color=\"info\">{m.passed}</font>\n"
            f"> 失败用例：<font color=\"comment\">{m.failed} 个</font>\n"
            f"> 异常用例：<font color=\"comment\">{m.broken} 个</font>\n"
            f"> 跳过用例：<font color=\"warning\">{m.skipped} 个</font>\n"
            f"> 执行时长：<font color=\"warning\">{m.time} s</font>\n"
            f"> 时间：<font color=\"comment\">{now_time}</font>\n"
            f">\n"
            f"> 非相关负责人员可忽略此消息。"
        )
        return self.send_markdown(text)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    @contextmanager
    def _open_file(self, path: str):
        """统一管理文件句柄（避免泄漏）。"""
        fh = open(path, "rb")
        try:
            yield fh
        finally:
            fh.close()

    @property
    def _upload_url(self) -> str:
        """从 webhook 中提取 key 构造 upload_media 接口地址。"""
        if not self.webhook:
            raise WebhookNotConfiguredError("WECHAT_WEBHOOK 未配置")
        qs = parse_qs(urlparse(self.webhook).query)
        key = qs.get("key", [None])[0]
        if not key:
            raise WeChatSendError(f"无法从 webhook 提取 key: {self.webhook}")
        return f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"

    def _upload_file(self, file: str) -> str:
        """上传文件到企业微信临时媒体库，返回 media_id。"""
        with self._open_file(file) as fh:
            res = self.session.post(
                self._upload_url, files={"file": fh}, timeout=self.timeout
            )
        data = res.json()
        if data.get("errcode") != 0:
            raise WeChatSendError(f"upload_media failed: {data}")
        return data["media_id"]

    def _post(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        统一 POST 逻辑：参数校验 + 重试 + 错误日志 + 业务错误返回。
        返回值：成功返回响应 dict；errcode != 0 也返回 dict（业务失败）；配置缺失返回 None。
        """
        if not self.webhook:
            logger.error("企业微信 Webhook 未配置")
            raise WebhookNotConfiguredError("WECHAT_WEBHOOK 未配置")

        last_err: Optional[Exception] = None
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                res = self.session.post(
                    self.webhook,
                    json=payload,
                    headers=self._HEADERS,
                    timeout=self.timeout,
                )
                data = res.json()
                if data.get("errcode") != 0:
                    logger.bind(msgtype=payload["msgtype"]).error(
                        f"企业微信「{payload['msgtype']}类型」消息发送失败: {data}"
                    )
                    return data
                return data
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                logger.warning(
                    f"企业微信发送网络错误 (attempt {attempt}/{attempts}): {e}"
                )
            except Exception as e:
                logger.exception(f"企业微信发送请求异常: {e}")
                raise WeChatSendError(f"企业微信发送异常: {e}") from e

        raise WeChatSendError(
            f"企业微信发送失败，已重试 {self.max_retries} 次"
        ) from last_err


if __name__ == "__main__":
    # 示例用法：
    # sender = WeChatSend()
    # sender.send_text("Hello", at_all=True)
    # sender.send_markdown("## 通知")
    # sender.send_wechat_notification(metrics)
    pass
