"""Google GenAI Provider（Gemini 出图 + Veo 出视频）

对接 Google 官方 genai SDK：
- 图片：models.generate_content(model=image_model, contents=prompt,
         config={"response_modalities": ["IMAGE"]})  —— 同步返回
- 视频：models.generate_videos(model=video_model, prompt=..., image=<PIL.Image>)
        异步轮询（operation.done）直到完成，结果落盘到
        MEDIA_ROOT/ai_studio/videos/{task_id}.mp4，返回可访问 URL

视频首帧（image-to-video）解析优先级：
1. task.first_frame（用户上传的文件，最高优先级，支持「上传」）
2. task.ref_image（data-url / 裸 base64 / http(s) URL / 本地路径）
3. 仅当渠道 config 显式开启 auto_first_frame=true 时，才用 prompt 让 Gemini
   先出一张图作为首帧（即"出图 -> 用图出视频"的串联）—— 不再是默认行为。
   未开启且前两者都缺失时，直接报错，要求用户上传首帧。

ApiChannel.config 示例：
{
    "provider": "google",
    "api_key_env": "GOOGLE_API_KEY",
    "image_model": "gemini-3.1-flash-image-preview",
    "video_model": "veo-3.1-generate-preview",
    "video_timeout": 300,        // 轮询总超时（秒）
    "video_poll_interval": 10,   // 轮询间隔（秒）
    "auto_first_frame": false   // 是否允许"无首帧时自动出图"串联（默认 false，需上传）
}

注意：本项目开发环境无 Celery broker，视频生成在 services.run_generation
内部同步轮询完成（贴合用户示例写法），因此会阻塞 HTTP 请求直到视频就绪；
生产环境建议切 AI_STUDIO_SYNC=False 并启动 Celery worker。
"""
from __future__ import annotations

import ast
import base64
import io
import json
import os
import time

from django.conf import settings
from google import genai
from loguru import logger
from PIL import Image

from .base import BaseProvider, ProviderError


class GoogleProvider(BaseProvider):
    key = 'google'

    # ---------- 客户端 ----------

    def _client(self) -> genai.Client:
        api_key = self.get_api_key()
        try:
            return genai.Client(api_key=api_key)
        except Exception as e:  # pragma: no cover - 客户端初始化失败
            raise self._map_error('客户端初始化', e) from e

    @staticmethod
    def _parse_google_error(exc) -> dict:
        """从 Google SDK 异常中提取干净的错误信息，避免把整段原始 JSON 透传给前端。

        Google 的报错形如：
          "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': '...',
           'status': '...', 'details': [{'@type': '...ErrorInfo', 'reason': '...'}]}}"
        这里只取出 error.message / error.status / details[].reason，丢弃嵌套结构。
        """
        raw = str(exc)
        info: dict = {'message': None, 'status': None, 'reason': None}
        start = raw.find('{')
        if start != -1:
            blob = raw[start:]
            payload = None
            # Google SDK 报错体可能是单引号 Python-dict 风格，也可能是标准 JSON，
            # 先试 json.loads，再回退 ast.literal_eval。
            try:
                payload = json.loads(blob)
            except (ValueError, TypeError):
                try:
                    payload = ast.literal_eval(blob)
                except (ValueError, SyntaxError, TypeError):
                    payload = None
            if isinstance(payload, dict):
                err = payload.get('error', {})
                if isinstance(err, dict):
                    info['message'] = err.get('message')
                    info['status'] = err.get('status')
                    for d in err.get('details', []) or []:
                        if isinstance(d, dict) and d.get('@type', '').endswith('ErrorInfo'):
                            info['reason'] = d.get('reason')
                            break
        return info

    @staticmethod
    def _map_error(stage: str, exc) -> ProviderError:
        """把 Google SDK 异常转成结构化 ProviderError（标准 code + 干净 message）。

        覆盖常见失败：key 无效 / 配额限流 / 超时 / 网络；其余归为 PROVIDER_ERROR。
        """
        raw = str(exc)
        low = raw.lower()
        info = GoogleProvider._parse_google_error(exc)
        # 干净可读原因：优先用 Google 返回的 error.message，否则退回原始文本首行
        reason = info.get('message') or (raw.splitlines()[0] if raw.strip() else raw)

        if any(k in low for k in ('api key', '401', '403', 'permission', 'unauthorized', 'authentication', 'api_key_invalid')):
            code = 'API_KEY_INVALID'
            zh = 'API Key 无效或未配置'
        elif any(k in low for k in ('429', 'quota', 'resource exhausted', 'rate limit', 'too many requests')):
            code = 'QUOTA_EXCEEDED'
            zh = '配额/限流不足'
        elif any(k in low for k in ('deadline', 'timeout', 'timed out')):
            code = 'TIMEOUT'
            zh = '请求超时'
        elif any(k in low for k in ('connection', 'network', 'name or service', 'failed to resolve', 'reset by peer')):
            code = 'NETWORK_ERROR'
            zh = '网络请求失败'
        else:
            code = 'PROVIDER_ERROR'
            zh = f'调用失败（{stage}）'

        message = f'Google {zh}（{stage}）'
        if reason and reason not in message:
            message += f'：{reason}'
        return ProviderError(message, code=code, stage=stage)

    # ---------- 图片相关工具 ----------

    @staticmethod
    def _part_to_pil(part) -> Image.Image | None:
        """从 GenerateContentResponse 的 Part 取图像字节并解码为 PIL Image。"""
        inline = getattr(part, 'inline_data', None)
        if inline is not None and getattr(inline, 'data', None):
            try:
                return Image.open(io.BytesIO(inline.data))
            except Exception as e:
                raise ProviderError(f'Gemini 返回图像解码失败: {e}') from e
        return None

    @staticmethod
    def _pil_to_data_url(img: Image.Image) -> str:
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')

    @staticmethod
    def _data_url_to_pil(data_url: str) -> Image.Image:
        """把 data-URL / 裸 base64 / http(s) URL / 本地文件路径 解析为 PIL Image。"""
        ref = (data_url or '').strip()
        # 本地已落盘的文件（如上传首帧经中转存为本地路径）直接打开
        if ref and (ref.startswith('/') or os.path.exists(ref)):
            try:
                return Image.open(ref)
            except Exception as e:
                raise ProviderError(f'本地首帧文件读取失败: {e}') from e
        if ref.startswith('data:'):
            _, b64 = ref.split(',', 1)
            raw = base64.b64decode(b64)
        elif ref.startswith('http://') or ref.startswith('https://'):
            import requests

            r = requests.get(ref, timeout=30)
            r.raise_for_status()
            raw = r.content
        else:
            raw = base64.b64decode(ref)
        return Image.open(io.BytesIO(raw))

    def _generate_image(self, client: genai.Client, task) -> list[str]:
        image_model = self.config.get('image_model', 'gemini-3.1-flash-image-preview')
        logger.info('[GOOGLE] 图像生成 model=%s prompt=%s', image_model, (task.prompt or '')[:40])
        try:
            resp = client.models.generate_content(
                model=image_model,
                contents=task.prompt,
                config={'response_modalities': ['IMAGE']},
            )
        except Exception as e:
            raise self._map_error('Gemini 图像生成', e) from e

        if not getattr(resp, 'candidates', None):
            raise ProviderError('Gemini 未返回任何候选结果')

        results: list[str] = []
        for cand in resp.candidates:
            parts = getattr(getattr(cand, 'content', None), 'parts', None) or []
            for part in parts:
                img = self._part_to_pil(part)
                if img is not None:
                    results.append(self._pil_to_data_url(img))
        if not results:
            raise ProviderError('Gemini 返回内容中未包含图像数据')
        return results[: max(1, int(task.count or 1))]

    # ---------- 视频相关工具 ----------

    def _resolve_input_image(self, client: genai.Client, task) -> Image.Image:
        """解析视频首帧（image-to-video 的输入图）。

        优先级：
        1) task.first_frame —— 用户上传的文件（支持「上传」）
        2) task.ref_image  —— data-url / base64 / URL / 本地路径
        3) 仅当 config.auto_first_frame=true 时，用 prompt 自动出图（串联）
        三者皆无则报错，要求上传首帧。
        """
        # 1) 上传的首帧文件（最高优先级）
        first_frame = getattr(task, 'first_frame', None)
        if first_frame:
            try:
                logger.info('[GOOGLE] 使用上传的首帧文件: %s', getattr(first_frame, 'name', first_frame))
                return Image.open(first_frame.path)
            except Exception as e:
                logger.warning('[GOOGLE] 读取上传首帧失败，回退到其它来源: %s', e)

        # 2) ref_image（兼容历史调用：data-url / base64 / URL）
        ref = (task.ref_image or '').strip()
        if ref:
            try:
                return self._data_url_to_pil(ref)
            except Exception as e:
                logger.warning('[GOOGLE] 解析 ref_image 失败，回退处理: %s', e)

        # 3) 显式开启时，用 prompt 自动出图作为首帧（串联，默认关闭）
        if self.config.get('auto_first_frame'):
            logger.info('[GOOGLE] 未提供首帧，按 auto_first_frame 用 prompt 出图作为首帧')
            imgs = self._generate_image(client, task)
            return self._data_url_to_pil(imgs[0])

        raise ProviderError(
            '视频生成需要首帧图像：请通过 first_frame 字段上传图片，'
            '或在 ref_image 中提供 data-url/base64/URL；'
            '或在渠道 config 开启 auto_first_frame 以用 prompt 自动出图。',
            code='NO_FIRST_FRAME',
        )

    @staticmethod
    def _save_video(video_file, task_id) -> str:
        rel = f'ai_studio/videos/{task_id}.mp4'
        abs_path = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        # google-genai 的 File.save() 会先把远程文件下载到本地再落盘
        try:
            video_file.save(abs_path)
        except Exception as e:
            raise ProviderError(f'Veo 视频保存失败: {e}') from e
        return f'{settings.MEDIA_URL}{rel}'

    def _generate_video(self, client: genai.Client, task) -> list[str]:
        video_model = self.config.get('video_model', 'veo-3.1-generate-preview')
        timeout = int(self.config.get('video_timeout', 300))
        interval = int(self.config.get('video_poll_interval', 10))
        logger.info('[GOOGLE] 视频生成 model=%s prompt=%s', video_model, (task.prompt or '')[:40])

        try:
            input_image = self._resolve_input_image(client, task)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f'视频参考帧准备失败: {e}') from e

        try:
            operation = client.models.generate_videos(
                model=video_model,
                prompt=task.prompt,
                image=input_image,
            )
        except Exception as e:
            raise self._map_error('Veo 视频生成提交', e) from e

        # 异步轮询直到完成（与用户示例一致）
        start = time.time()
        while not operation.done:
            waited = time.time() - start
            if waited > timeout:
                raise ProviderError(f'Veo 视频生成超时（已等待 {int(waited)}s > {timeout}s）')
            logger.info('[GOOGLE] 视频生成中... 已等待 %.0fs', waited)
            time.sleep(interval)
            operation = client.operations.get(operation)

        try:
            generated = operation.response.generated_videos[0]
        except (AttributeError, IndexError, TypeError) as e:
            raise ProviderError(f'Veo 返回结构异常: {e}') from e

        # 记录 operation name，便于以后扩展回调 / 查询
        task.external_task_id = getattr(operation, 'name', None)
        task.save(update_fields=['external_task_id'])

        url = self._save_video(generated.video, task.id)
        return [url]

    # ---------- 核心接口 ----------

    def supports(self, kind: str) -> bool:
        # 同步 API 报错更友好；此处标记支持 image / video
        return (kind or '').lower() in ('image', 'video')

    def generate(self, task) -> list[str]:
        kind = (task.kind or '').lower()
        client = self._client()
        if kind == 'image':
            return self._generate_image(client, task)
        if kind == 'video':
            return self._generate_video(client, task)
        raise ProviderError(f'Google provider 不支持的生成类型: {task.kind}')
