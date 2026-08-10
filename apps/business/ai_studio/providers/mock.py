"""mock Provider：离线占位生成（默认渠道 / 无渠道时使用）

从 services.run_mock_generation 迁移而来，行为不变：
模拟推理耗时并产出渐变占位图（data-URL SVG）。
"""
import base64
import random
import time

from .base import BaseProvider

_GRADIENTS = [
    ('#7c5cff', '#37c6ff'),
    ('#ff7eb3', '#ff758c'),
    ('#43e97b', '#38f9d7'),
    ('#fa709a', '#fee140'),
    ('#30cfd0', '#330867'),
    ('#a8edea', '#fed6e3'),
]


def _make_placeholder(seed: int, label: str) -> str:
    c1, c2 = _GRADIENTS[seed % len(_GRADIENTS)]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{c1}"/>'
        f'<stop offset="100%" stop-color="{c2}"/>'
        '</linearGradient></defs>'
        '<rect width="600" height="600" fill="url(#g)"/>'
        '<text x="50%" y="50%" font-size="140" text-anchor="middle" '
        'dominant-baseline="middle">🛍️</text>'
        f'<text x="50%" y="92%" font-size="22" fill="rgba(255,255,255,.85)" '
        f'text-anchor="middle">{label}</text></svg>'
    )
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return 'data:image/svg+xml;base64,' + encoded


class MockProvider(BaseProvider):
    key = 'mock'

    def supports(self, kind: str) -> bool:
        return True  # 图片/视频都支持占位

    def generate(self, task) -> list[str]:
        time.sleep(random.uniform(1.2, 3.0))  # 模拟推理耗时
        return [
            _make_placeholder(i, (task.prompt or 'AI')[:10])
            for i in range(task.count)
        ]
