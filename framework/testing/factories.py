"""
轻量 model factory（不依赖 factory_boy）。

若项目已安装 factory_boy，推荐直接使用它；此基类仅在没有 factory_boy 时提供
最小可用的 ``create`` / ``build`` 能力，避免测试对第三方库产生硬依赖。
"""
from typing import Any, Dict, Optional

from django.db import models


class ModelFactory:
    model: Optional[type] = None
    defaults: Dict[str, Any] = {}

    @classmethod
    def create(cls, **kwargs):
        if cls.model is None:
            raise NotImplementedError("ModelFactory.model 必须指定")
        attrs = {**cls.defaults, **kwargs}
        return cls.model.objects.create(**attrs)

    @classmethod
    def build(cls, **kwargs):
        if cls.model is None:
            raise NotImplementedError("ModelFactory.model 必须指定")
        attrs = {**cls.defaults, **kwargs}
        return cls.model(**attrs)
