"""飞书机器人通知。

封装飞书自定义机器人 webhook 发送（文本 / Markdown / 富文本），支持加签安全设置。
渠道开关与地址由 settings / 环境变量注入。
"""
import base64
import hashlib
import hmac
import json
import logging
import time
import datetime
import requests
import urllib3
from django.conf import settings

from framework.helpers.system_config import get_local_ip

urllib3.disable_warnings()

try:
    JSONDecodeError = json.decoder.JSONDecodeError
except AttributeError:
    JSONDecodeError = ValueError

def is_not_null_and_blank_str(content):
    """
    非空字符串
    :param content: 字符串
    :return: 非空 - True，空 - False
    """
    return bool(content and content.strip())

class FeiShuTalkChatBot:
    """飞书机器人通知"""

    def __init__(self, metrics=None):
        self.metrics = metrics
        self.sign = self.get_sign()


    def get_sign(self):
        self.timestamp = str(round(time.time()))
        secret = settings.FEISHU_SECRET
        secret_enc = secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(self.timestamp, secret)
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign

    def send_text(self, msg: str):
        """
        发送纯文本消息
        """
        if not is_not_null_and_blank_str(msg):
            logging.error("text类型，消息内容不能为空！")
            return

        payload = {
            "msg_type": "text",
            "content": {"text": msg},
            "timestamp": self.timestamp,
            "sign": self.sign
        }
        return self._do_post(payload)

    def _do_post(self, payload):
        headers = {'Content-Type': 'application/json; charset=utf-8'}
        webhook = settings.FEISHU_WEBHOOK
        if not webhook:
            logging.error("FEISHU_WEBHOOK 未配置")
            return
            
        try:
            response = requests.post(
                webhook,
                headers=headers,
                data=json.dumps(payload),
                verify=False,
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('code') != 0:
                logging.error(f"飞书消息发送失败: {result}")
            return result
        except Exception as e:
            logging.error(f"飞书请求异常: {e}")
            return None

    def post(self):
        """
        发送自动化测试报告卡片
        """
        if not self.metrics:
            logging.error("metrics 不能为空！")
            return
            
        is_all_testcase_passed = getattr(self.metrics, 'total', 0) == getattr(self.metrics, 'passed', 0)
        header_color = "blue" if is_all_testcase_passed else "red"
        header_text = "🎉 自动化测试通过~" if is_all_testcase_passed else "😱 有失败的用例！"
        
        project_name = getattr(settings, 'PROJECT_NAME', 'DjangoProject')
        tester_name = getattr(settings, 'TESTER_NAME', 'Admin')
        env = getattr(settings, 'ENV', 'TEST')
        pass_rate = getattr(self.metrics, 'pass_rate', 0)
        total = getattr(self.metrics, 'total', 0)
        passed = getattr(self.metrics, 'passed', 0)
        failed = getattr(self.metrics, 'failed', 0)
        broken = getattr(self.metrics, 'broken', 0)
        skipped = getattr(self.metrics, 'skipped', 0)
        
        rich_text = {
            "msg_type": "interactive",
            "card": {
                "elements": [
                    {"tag": "markdown", "content": f"**🤖 测试人员： {tester_name}**"},
                    {"tag": "markdown", "content": f"**🚀 运行环境： {env}**"},
                    {"tag": "markdown", "content": f"**💌 成功率： {pass_rate} %**"},
                    {"tag": "markdown", "content": f"**🎖️ 用例数： {total}**"},
                    {"tag": "markdown", "content": f"**⭕ 成功用例： {passed}**"},
                    {"tag": "markdown", "content": f"**❌ 失败用例： {failed}**"},
                    {"tag": "markdown", "content": f"**❗ 异常用例： {broken}**"},
                    {"tag": "markdown", "content": f"**❓ 跳过用例： {skipped}**"},
                    {"tag": "markdown", "content": f"📅 时间： {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"},
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "报告详情"},
                                "type": "primary",
                                "url": get_local_ip() if callable(get_local_ip) else get_local_ip
                            }
                        ]
                    }
                ],
                "header": {
                    "template": header_color,
                    "title": {"content": header_text, "tag": "plain_text"}
                }
            }
        }
        
        # 添加签名和时间戳
        rich_text["timestamp"] = self.timestamp
        rich_text["sign"] = self.sign
        
        return self._do_post(rich_text)






# metrics_instance = TestMetrics(passed=80, failed=10, broken=5, skipped=5, total=100, pass_rate=80.0,time = '2024/01/05')
# bot = FeiShuTalkChatBot(metrics_instance)
# # 调用发送文本消息的方法示例
# msg = "自动化测试完成！"
# bot.send_text(msg)
# bot.post()
