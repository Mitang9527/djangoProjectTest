"""Provider 注册表 + 渠道配置解析

渠道配置来源（优先级从高到低）：
1. ApiChannel.config 内联完整配置（含 "provider" 字段时直接使用，向后兼容）；
2. ApiChannel.config = {"profile": "xxx"} → 读 config/channels.json 中对应档案；
3. ApiChannel.config 为空 → 按渠道名称匹配 channels.json 中的档案名；
4. 都没有 → channels.json 的 "default" 档案（mock）。

channels.json 里返回的档案可被 ApiChannel.config 中的同名字段覆盖
（如文件里定义了档案，某渠道想单独换 model，只需在 DB 里写
{"profile": "xxx", "model": "另一个模型"}）。

配置文件路径可用 settings.AI_STUDIO_CHANNELS_JSON 覆盖，
默认 apps/business/ai_studio/config/channels.json。

新增第三方接入步骤：
1. 在 providers/ 下新建 xxx.py，实现 BaseProvider 子类（key 唯一）；
2. 在下方 PROVIDERS 注册；
3. 在 config/channels.json 添加一个档案，渠道引用它即可。
"""
import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .base import BaseProvider, ProviderError
from .mock import MockProvider
from .openai import OpenAIProvider
from .google import GoogleProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    MockProvider.key: MockProvider,
    OpenAIProvider.key: OpenAIProvider,
    GoogleProvider.key: GoogleProvider,
}

DEFAULT_PROVIDER = MockProvider.key

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'channels.json'


@lru_cache(maxsize=1)
def load_channel_profiles() -> dict:
    """读取渠道配置文件（带缓存；修改文件后重启进程或调 load_channel_profiles.cache_clear()）。"""
    path = Path(getattr(settings, 'AI_STUDIO_CHANNELS_JSON', None) or _DEFAULT_CONFIG_PATH)
    if not path.exists():
        return {'default': {'provider': DEFAULT_PROVIDER}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as e:
        raise ProviderError(f'渠道配置文件解析失败 {path}: {e}') from e
    return {k: v for k, v in data.items() if not k.startswith('_')}


def resolve_channel_config(channel) -> dict:
    """合并渠道最终生效的生成配置（DB 字段覆盖文件档案）。"""
    db_cfg = dict(channel.config or {}) if channel is not None else {}
    if 'provider' in db_cfg:
        return db_cfg  # 内联完整配置，直接用

    profiles = load_channel_profiles()
    profile_key = db_cfg.pop('profile', None) or (channel.name if channel else None)
    file_cfg = dict(profiles.get(profile_key) or profiles.get('default') or {})
    if not file_cfg:
        file_cfg = {'provider': DEFAULT_PROVIDER}
    file_cfg.update(db_cfg)  # DB 同名字段覆盖文件档案
    return file_cfg


def get_provider(channel=None) -> BaseProvider:
    """按渠道最终配置返回 Provider 实例；无渠道时回退 default（mock）。"""
    cfg = resolve_channel_config(channel)
    key = cfg.get('provider', DEFAULT_PROVIDER)
    cls = PROVIDERS.get(key)
    if cls is None:
        raise ProviderError(f'未注册的 provider: {key}（渠道配置有误）')
    provider = cls(channel)
    provider.config = cfg  # 使用合并后的最终配置
    return provider


__all__ = [
    'BaseProvider', 'ProviderError', 'PROVIDERS',
    'get_provider', 'resolve_channel_config', 'load_channel_profiles',
]
