"""
测试中使用的 API 客户端封装。

注意：DRF 的 ``rest_framework.test.APIClient`` 在导入期会访问 Django settings，
因此这里采用惰性组合（实例化时才 import），保证 ``import framework.testing``
本身不依赖 Django setup，可在任何环境下安全导入。
"""
from typing import Any


class JWTAPIClient:
    """封装 DRF APIClient，提供一行设置 Bearer token 的能力。"""

    def __init__(self):
        from rest_framework.test import APIClient

        self._client = APIClient()

    def set_jwt(self, token: str) -> None:
        """携带 Bearer token 发起鉴权请求。"""
        self._client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def __getattr__(self, name: str) -> Any:
        # 未显式定义的属性/方法转发给内部 APIClient
        return getattr(self._client, name)
