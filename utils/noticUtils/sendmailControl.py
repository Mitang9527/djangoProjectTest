"""
描述: 发送邮件
"""

import smtplib
from email.mime.text import MIMEText
from django.conf import settings


class SendEmail:
    """ 发送邮箱 """
    def __init__(self, metrics=None):
        self.metrics = metrics

    @classmethod
    def send_mail(cls, user_list: list, sub, content: str) -> None:
        """

        @param user_list: 发件人邮箱
        @param sub:
        @param content: 发送内容
        @return:
        """
        send_user = settings.EMAIL_SEND_USER
        email_host = settings.EMAIL_HOST
        stamp_key = settings.EMAIL_STAMP_KEY
        
        user = "Admin" + "<" + send_user + ">"
        message = MIMEText(content, _subtype='plain', _charset='utf-8')
        message['Subject'] = sub
        message['From'] = user
        message['To'] = ";".join(user_list)
        server = smtplib.SMTP()
        server.connect(email_host)
        server.login(send_user, stamp_key)
        server.sendmail(user, user_list, message.as_string())
        server.close()

    def error_mail(self, error_message: str) -> None:
        """
        执行异常邮件通知
        @param error_message: 报错信息
        @return:
        """
        email = settings.EMAIL_SEND_LIST
        user_list = email.split(',')  # 多个邮箱发送，config文件中直接添加  '邮箱@qq.com'
        project_name = getattr(settings, 'PROJECT_NAME', 'DjangoProject')

        sub = project_name + "接口自动化执行异常通知"
        content = f"自动化测试执行完毕，程序中发现异常，请悉知。报错信息如下：\n{error_message}"
        self.send_mail(user_list, sub, content)

    def send_main(self) -> None:
        """
        发送邮件
        :return:
        """
        if not self.metrics:
            return
            
        email = settings.EMAIL_SEND_LIST
        user_list = email.split(',')  # 多个邮箱发送，yaml文件中直接添加  '邮箱@qq.com'
        project_name = getattr(settings, 'PROJECT_NAME', 'DjangoProject')

        sub = project_name + "接口自动化报告"
        content = f"""
        各位同事, 大家好:
            自动化用例执行完成，执行结果如下:
            用例运行总数: {self.metrics.total} 个
            通过用例个数: {self.metrics.passed} 个
            失败用例个数: {self.metrics.failed} 个
            异常用例个数: {self.metrics.broken} 个
            跳过用例个数: {self.metrics.skipped} 个
            成  功   率: {self.metrics.pass_rate} %

        详细情况可登录jenkins平台查看，非相关负责人员可忽略此消息。谢谢。
        """
        self.send_mail(user_list, sub, content)


if __name__ == '__main__':
    # 示例用法
    # sender = SendEmail(metrics)
    # sender.send_main()
    pass
