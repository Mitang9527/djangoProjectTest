"""Soul 示例应用（脚手架 demo）。

仅含一个 Soul 模型作为 Django App 结构的最小示例，用于演示路由/序列化/视图的
标准搭建方式；非业务模块，可作为新业务 App 的起步模板。
"""

from django.db import models

class Soul(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
