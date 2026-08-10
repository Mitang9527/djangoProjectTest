"""OpenAI 兼容接口 Provider（文生图）

对接标准 POST {base_url}/images/generations，适用于 OpenAI 及一切
兼容该协议的第三方网关（One-API / New-API / Azure 代理 / 各类中转站）。

ApiChannel.config 示例：
{
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",      // 可换成任意兼容网关
    "api_key_env": "OPENAI_API_KEY",              // 密钥环境变量名（推荐）
    "model": "dall-e-3",                           // 或 gpt-image-1 等
    "response_format": "url",                      // url | b64_json
    "one_per_request": true,                       // dall-e-3 等 n 只能为 1 时开启
    "timeout": 120,
    "size_map": {"1:1": "1024x1024", ...}          // 可选，覆盖默认比例映射
}
"""
from __future__ import annotations

import requests
from loguru import logger

from .base import BaseProvider, ProviderError

# task.size(宽高比) -> OpenAI size 参数的默认映射
DEFAULT_SIZE_MAP = {
    '1:1': '1024x1024',
    '16:9': '1792x1024',
    '9:16': '1024x1792',
    '4:3': '1024x1024',
    '3:4': '1024x1024',
}

# resolution -> quality（仅部分模型支持，可在 config 用 quality_map 覆盖）
DEFAULT_QUALITY_MAP = {
    'standard': 'standard',
    'hd': 'hd',
    '4k': 'hd',
}


class OpenAIProvider(BaseProvider):
    key = 'openai'

    def _endpoint(self) -> str:
        base = (self.config.get('base_url') or 'https://api.openai.com/v1').rstrip('/')
        return f'{base}/images/generations'

    def _build_payload(self, task, n: int) -> dict:
        size_map = {**DEFAULT_SIZE_MAP, **self.config.get('size_map', {})}
        quality_map = {**DEFAULT_QUALITY_MAP, **self.config.get('quality_map', {})}
        payload = {
            'model': self.config.get('model', 'dall-e-3'),
            'prompt': task.prompt,
            'n': n,
            'size': size_map.get(task.size, '1024x1024'),
            'response_format': self.config.get('response_format', 'url'),
        }
        quality = quality_map.get(task.resolution)
        if quality and self.config.get('pass_quality', True):
            payload['quality'] = quality
        return payload

    def _call_once(self, task, n: int) -> list[str]:
        timeout = int(self.config.get('timeout', 120))
        headers = {
            'Authorization': f'Bearer {self.get_api_key()}',
            'Content-Type': 'application/json',
        }
        try:
            resp = requests.post(
                self._endpoint(),
                json=self._build_payload(task, n),
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise ProviderError(f'请求第三方接口失败: {e}') from e

        if resp.status_code != 200:
            body = resp.text[:500]
            logger.warning('OpenAI 兼容接口报错 status=%s body=%s', resp.status_code, body)
            raise ProviderError(f'第三方接口返回 {resp.status_code}: {body}')

        try:
            data = resp.json().get('data') or []
        except ValueError as e:
            raise ProviderError(f'第三方接口响应非 JSON: {resp.text[:200]}') from e

        results = []
        for item in data:
            if item.get('url'):
                results.append(item['url'])
            elif item.get('b64_json'):
                results.append('data:image/png;base64,' + item['b64_json'])
        if not results:
            raise ProviderError('第三方接口未返回任何结果')
        return results

    def generate(self, task) -> list[str]:
        # 注意：API 层写入的 kind 是小写（image/video），统一转小写比较
        if (task.kind or '').lower() != 'image':
            raise ProviderError('该渠道（OpenAI 兼容 images 接口）暂不支持视频生成')

        # dall-e-3 等模型单次只能 n=1：逐张请求
        if self.config.get('one_per_request', False) and task.count > 1:
            results: list[str] = []
            for _ in range(task.count):
                results.extend(self._call_once(task, 1))
            return results

        return self._call_once(task, task.count)
