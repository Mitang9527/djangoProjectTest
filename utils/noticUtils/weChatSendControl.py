"""
描述: 发送企业微信通知
"""

import requests
from loguru import logger
from datetime import datetime
from django.conf import settings


class WeChatSend:
    """
    企业微信消息通知
    """

    def __init__(self, metrics=None):
        self.metrics = metrics
        self.headers = {"Content-Type": "application/json"}

    def send_text(self, content, mentioned_mobile_list=None):
        """
        发送文本类型通知
        """
        _data = {"msgtype": "text", "text": {"content": content, "mentioned_list": None,
                                             "mentioned_mobile_list": mentioned_mobile_list}}

        webhook = settings.WECHAT_WEBHOOK
        if not webhook:
            logger.error("企业微信 Webhook 未配置")
            return

        try:
            res = requests.post(url=webhook, json=_data, headers=self.headers, timeout=10)
            res_json = res.json()
            if res_json.get('errcode') != 0:
                logger.error(f"企业微信「文本类型」消息发送失败: {res_json}")
            return res_json
        except Exception as e:
            logger.error(f"企业微信发送请求异常: {e}")
            return None

    def send_markdown(self, content):
        """
        发送 MarkDown 类型消息
        """
        _data = {"msgtype": "markdown", "markdown": {"content": content}}
        webhook = settings.WECHAT_WEBHOOK
        if not webhook:
            return

        try:
            res = requests.post(url=webhook, json=_data, headers=self.headers, timeout=10)
            res_json = res.json()
            if res_json.get('errcode') != 0:
                logger.error(f"企业微信「MarkDown类型」消息发送失败: {res_json}")
            return res_json
        except Exception as e:
            logger.error(f"企业微信发送请求异常: {e}")
            return None

    def _upload_file(self, file):
        """
        先将文件上传到临时媒体库
        """
        webhook = settings.WECHAT_WEBHOOK
        key = webhook.split("key=")[1]
        url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"
        data = {"file": open(file, "rb")}
        res = requests.post(url, files=data).json()
        return res['media_id']

    def send_file_msg(self, file):
        """
        发送文件类型的消息
        @return:
        """

        _data = {"msgtype": "file", "file": {"media_id": self._upload_file(file)}}
        webhook = settings.WECHAT_WEBHOOK
        res = requests.post(url=webhook, json=_data, headers=self.headers)
        if res.json()['errcode'] != 0:
            logger.error(res.json())
            raise Exception("企业微信「file类型」消息发送失败")

    def send_wechat_notification(self):
        """ 发送企业微信通知 """
        if not self.metrics:
            return
            
        project_name = getattr(settings, 'PROJECT_NAME', 'DjangoProject')
        tester_name = getattr(settings, 'TESTER_NAME', 'Admin')
        now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        text = f"""【{project_name}自动化通知】
                                    >测试环境：<font color=\"info\">TEST</font>
                                    >测试负责人：@{tester_name}
                                    >
                                    > **执行结果**
                                    ><font color=\"info\">成  功  率  : {self.metrics.pass_rate}%</font>
                                    >用例  总数：<font color=\"info\">{self.metrics.total}</font>                                    
                                    >成功用例数：<font color=\"info\">{self.metrics.passed}</font>
                                    >失败用例数：`{self.metrics.failed}个`
                                    >异常用例数：`{self.metrics.broken}个`
                                    >跳过用例数：<font color=\"warning\">{self.metrics.skipped}个</font>
                                    >用例执行时长：<font color=\"warning\">{self.metrics.time} s</font>
                                    >时间：<font color=\"comment\">{now_time}</font>
                                    >
                                    >非相关负责人员可忽略此消息。"""

        self.send_markdown(text)


if __name__ == '__main__':
    # 示例用法
    # sender = WeChatSend(metrics)
    # sender.send_wechat_notification()
    pass
