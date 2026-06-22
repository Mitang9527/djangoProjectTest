
import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Any, Text
from dingtalkchatbot.chatbot import DingtalkChatbot, FeedLink
from django.conf import settings
from loguru import logger


class DingTalkSendMsg:
    """ 发送钉钉通知 """
    def __init__(self, metrics=None):
        self.metrics = metrics
        self.timeStamp = str(round(time.time() * 1000))

    def xiao_ding(self):
        sign = self.get_sign()
        # 从 Django settings 中获取配置信息
        webhook = f"{settings.DINGTALK_WEBHOOK}&timestamp={self.timeStamp}&sign={sign}"
        return DingtalkChatbot(webhook)

    def get_sign(self) -> Text:
        """
        根据时间戳 + "sign" 生成密钥
        :return:
        """
        secret = settings.DINGTALK_SECRET
        string_to_sign = f'{self.timeStamp}\n{secret}'.encode('utf-8')
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign,
            digestmod=hashlib.sha256).digest()

        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return sign

    def send_text(
            self,
            msg: Text,
            mobiles=None
    ) -> None:
        """
        发送文本信息
        :param msg: 文本内容
        :param mobiles: 艾特用户电话
        :return:
        """
        try:
            if not mobiles:
                self.xiao_ding().send_text(msg=msg, is_at_all=True)
            else:
                if isinstance(mobiles, list):
                    self.xiao_ding().send_text(msg=msg, at_mobiles=mobiles)
                else:
                    logger.error(f"mobiles 类型错误: {type(mobiles)}")
                    # 容错处理：尝试作为单个手机号发送
                    self.xiao_ding().send_text(msg=msg, at_mobiles=[str(mobiles)])
        except Exception as e:
            logger.error(f"钉钉发送文本消息异常: {e}")

    def send_link(
            self,
            title: Text,
            text: Text,
            message_url: Text,
            pic_url: Text
    ) -> None:
        """
        发送link通知
        :return:
        """
        self.xiao_ding().send_link(
                title=title,
                text=text,
                message_url=message_url,
                pic_url=pic_url
            )

    def send_markdown(self, title, msg, is_at_all=False):
        """ 发送markdown消息 """
        try:
            xiao_ding = self.xiao_ding()
            if not xiao_ding:
                return
            xiao_ding.send_markdown(title=title, text=msg, is_at_all=is_at_all)
        except Exception as e:
            logger.error(f"钉钉发送异常: {e}")

    @staticmethod
    def feed_link(
            title: Text,
            message_url: Text,
            pic_url: Text
    ) -> Any:
        """ FeedLink 二次封装 """
        return FeedLink(
            title=title,
            message_url=message_url,
            pic_url=pic_url
        )

    def send_feed_link(self, *arg) -> None:
        """发送 feed_lik """

        self.xiao_ding().send_feed_card(list(arg))

    def send_ding_notification(self):
        """ 发送钉钉报告通知 """
        if not settings.DINGTALK_WEBHOOK:
            return
            
        # 判断如果有失败的用例，@所有人
        is_at_all = False
        if self.metrics and (getattr(self.metrics, 'failed', 0) + getattr(self.metrics, 'broken', 0) > 0):
            is_at_all = True
        
        project_name = getattr(settings, 'PROJECT_NAME', 'DjangoProject')
        tester_name = getattr(settings, 'TESTER_NAME', 'Admin')
        env = getattr(settings, 'ENV', 'TEST')

        text = f"#### {project_name}自动化通知  " \
               f"\n\n>Python脚本任务: {project_name}" \
               f"\n\n>环境: {env}\n\n>" \
               f"执行人: {tester_name}"
        
        self.send_markdown(
            title="【接口自动化通知】",
            msg=text,
            is_at_all=is_at_all
        )

