"""AI 创作工作室 - 第三方 Provider 抽象接口

所有外部生成 API（OpenAI 兼容、豆包、自建 Agent 等）都实现 BaseProvider，
由 providers.registry 按 ApiChannel.config['provider'] 分发。

约定：
- generate() 同步返回结果 URL / data-URL 列表；
- 失败抛异常，由上层（services.run_generation / tasks）负责 FAILED + refund；
- 密钥不写库：config 里只放 api_key_env（环境变量名），真实 key 放环境变量。
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import ApiChannel, GenerationTask


class ProviderError(Exception):
    """第三方调用失败的统一异常。

    message 会写入 task.error_msg；code 为标准化错误码（如 API_KEY_INVALID），
    便于前端按 code 做差异化提示、也便于日志与统计。
    """

    def __init__(self, message: str, code: str = 'PROVIDER_ERROR', stage: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.stage = stage

    def __str__(self) -> str:
        return self.message


class BaseProvider:
    """生成渠道适配基类"""

    key = ''  # 与 ApiChannel.config['provider'] 对应，如 'openai'

    def __init__(self, channel: 'ApiChannel | None' = None):
        self.channel = channel
        self.config: dict = (channel.config or {}) if channel else {}

    # ---- 通用工具 ----

    def get_api_key(self) -> str:
        """按引用从环境变量取密钥；兼容 config 直写 api_key（不推荐）。"""
        env_name = self.config.get('api_key_env')
        if env_name:
            key = os.environ.get(env_name, '')
            if not key:
                raise ProviderError(f'未配置环境变量 {env_name}')
            return key
        key = self.config.get('api_key', '')
        if not key:
            raise ProviderError('渠道未配置 API 密钥（api_key_env / api_key）')
        return key

    def supports(self, kind: str) -> bool:
        """是否支持该生成类型（image / video，大小写不敏感），子类按需覆盖"""
        return (kind or '').lower() == 'image'

    # ---- 核心接口 ----

    def generate(self, task: 'GenerationTask') -> list[str]:
        """执行生成，返回结果 URL / data-URL 列表。失败抛 ProviderError。"""
        raise NotImplementedError
