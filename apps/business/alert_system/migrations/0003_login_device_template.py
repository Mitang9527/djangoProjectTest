"""播种「新设备登录提醒」消息模板（code=login_new_device）。

由 system.users.login_security.maybe_notify_new_device_login 消费；
模板缺失/停用时回退默认硬编码文案，管理员可编辑此模板自定义提示语。
占位符：{time} {ip} {device}（渲染缺失键会 KeyError → 回退默认文案）。
"""
from django.db import migrations

TEMPLATE_CODE = "login_new_device"
TITLE = "新设备登录提醒"
CONTENT = (
    "您的账号于 {time} 在 {ip}（{device}）登录。如非本人操作，"
    "请立即修改密码并在「会话管理」中下线可疑设备。"
)


def seed_template(apps, schema_editor):
    MessageTemplate = apps.get_model("alert_system", "MessageTemplate")
    MessageTemplate.objects.update_or_create(
        code=TEMPLATE_CODE,
        defaults={
            "title": TITLE,
            "content": CONTENT,
            "html_content": "",
            "is_active": True,
        },
    )


def unseed_template(apps, schema_editor):
    MessageTemplate = apps.get_model("alert_system", "MessageTemplate")
    MessageTemplate.objects.filter(code=TEMPLATE_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("alert_system", "0002_messagetemplate_inappmessage"),
    ]

    operations = [
        migrations.RunPython(seed_template, unseed_template),
    ]
