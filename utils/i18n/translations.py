# sync-init: skip
"""
数据库动态翻译后端
==================

解决运营/租户后台需要动态改文案的需求：

- 提供可热更新的翻译存储（默认基于 Django cache，零依赖）
- 可选接入 ORM 模型（utils_translation 表）
- LRU 缓存层
- 注册/反注册 API
- 翻译完整度统计

设计取舍
--------

- 默认后端用 cache（无需 DB migration），运营场景够用
- 提供 ORMBackend 作为示例/扩展，调用方按需启用
- 缓存 key 形如 ``i18n:{lang}:{key}``，TTL 1 小时
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Iterable, Optional

from django.conf import settings
from django.core.cache import cache

from .exceptions import TranslationNotFoundError

logger = logging.getLogger(__name__)


# ============================================================
# 抽象基类
# ============================================================


class TranslationBackend:
    """翻译后端接口"""

    def get(self, key: str, lang: str) -> str | None:
        """按 key + lang 查翻译；找不到返回 None"""
        raise NotImplementedError

    def set(self, key: str, lang: str, value: str) -> None:
        """写入/覆盖翻译"""
        raise NotImplementedError

    def delete(self, key: str, lang: str | None = None) -> None:
        """删除翻译；lang=None 表示删全部语言"""
        raise NotImplementedError

    def get_many(self, keys: Iterable[str], lang: str) -> dict[str, str]:
        """批量查"""
        raise NotImplementedError

    def list_keys(self) -> list[str]:
        """列出所有 key"""
        raise NotImplementedError

    def stats(self, lang: str) -> dict[str, Any]:
        """统计完整度：total / translated / missing / coverage"""
        raise NotImplementedError

    def clear_cache(self) -> None:
        """清缓存（热更新时调用）"""
        raise NotImplementedError


# ============================================================
# CacheBackend：基于 Django cache（零 DB 依赖）
# ============================================================


class CacheTranslationBackend(TranslationBackend):
    """
    基于 Django cache 的翻译后端。

    - 适用场景：少量翻译（<10k 条），需要热更新
    - 不持久化：cache 重启数据丢失（生产建议同时持久到 DB）
    - 内存后端：实例级 dict 存储
    """

    CACHE_PREFIX = "i18n:db"
    CACHE_TTL = 3600  # 1 小时

    def __init__(self):
        # 实例级存储（避免 thread-local 跨实例污染）
        self._store: dict[str, dict[str, str]] = {}
        # 启动时从 cache 恢复
        self._load_from_cache()

    def _load_from_cache(self) -> None:
        """从共享 cache 加载所有翻译到内存"""
        try:
            data = cache.get(f"{self.CACHE_PREFIX}:_all_")
            if isinstance(data, dict):
                self._store.update(data)
        except Exception as e:
            logger.debug("Load i18n cache failed: %s", e)

    def _persist_to_cache(self) -> None:
        """把内存中所有翻译写回 cache"""
        try:
            cache.set(
                f"{self.CACHE_PREFIX}:_all_",
                self._store,
                timeout=self.CACHE_TTL,
            )
        except Exception as e:
            logger.warning("Persist i18n cache failed: %s", e)

    def get(self, key: str, lang: str) -> str | None:
        lang_dict = self._store.get(key)
        if not lang_dict:
            return None
        return lang_dict.get(lang)

    def set(self, key: str, lang: str, value: str) -> None:
        if key not in self._store:
            self._store[key] = {}
        self._store[key][lang] = value
        self._persist_to_cache()

    def delete(self, key: str, lang: str | None = None) -> None:
        if lang is None:
            self._store.pop(key, None)
        else:
            lang_dict = self._store.get(key)
            if lang_dict:
                lang_dict.pop(lang, None)
                if not lang_dict:
                    self._store.pop(key, None)
        self._persist_to_cache()

    def get_many(self, keys: Iterable[str], lang: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for k in keys:
            v = self.get(k, lang)
            if v is not None:
                out[k] = v
        return out

    def list_keys(self) -> list[str]:
        return list(self._store.keys())

    def stats(self, lang: str) -> dict[str, Any]:
        total = len(self._store)
        translated = sum(1 for k, v in self._store.items() if lang in v)
        missing = total - translated
        coverage = (translated / total) if total > 0 else 1.0
        return {
            "lang": lang,
            "total_keys": total,
            "translated": translated,
            "missing": missing,
            "coverage": round(coverage, 4),
        }

    def clear_cache(self) -> None:
        self._store.clear()
        try:
            cache.delete(f"{self.CACHE_PREFIX}:_all_")
        except Exception:
            pass


# ============================================================
# ORMBackend：基于 ORM 模型（可选启用）
# ============================================================


class ORMTranslationBackend(TranslationBackend):
    """
    基于 ORM 的翻译后端。

    用法::

        # 1) 继承并实现 _model_cls：
        from myapp.models import TranslationEntry
        backend = ORMTranslationBackend(_model_cls=TranslationEntry)

        # 2) 或者使用默认的 utils_translation 表（需要在 models.py 注册）

    模型字段约定：
        - key: CharField
        - lang: CharField
        - value: TextField
        - (key, lang) unique
    """

    DEFAULT_MODEL = None  # 延迟解析避免 AppConfig 顺序问题

    def __init__(self, _model_cls=None):
        self._model_cls = _model_cls or self._resolve_model()
        # 内存 LRU 缓存：避免每次都打 DB
        self._mem: dict[str, str] = {}
        self._hits = 0
        self._misses = 0

    def _resolve_model(self):
        """从 utils.i18n.models 解析默认模型（如果存在）"""
        try:
            from .models import Translation
            return Translation
        except ImportError:
            return None

    def _ensure_model(self):
        if self._model_cls is None:
            raise TranslationNotFoundError(
                "<no model>", "<no lang>"
            )  # 实际不会到这里，下面会抛
        return self._model_cls

    def get(self, key: str, lang: str) -> str | None:
        cache_key = f"{lang}:{key}"
        if cache_key in self._mem:
            self._hits += 1
            return self._mem[cache_key]
        self._misses += 1

        Model = self._ensure_model()
        try:
            obj = Model.objects.filter(key=key, lang=lang).first()
        except Exception as e:
            logger.debug("ORM i18n query failed: %s", e)
            return None
        if not obj:
            return None
        val = obj.value
        self._mem[cache_key] = val
        return val

    def set(self, key: str, lang: str, value: str) -> None:
        Model = self._ensure_model()
        try:
            Model.objects.update_or_create(
                key=key, lang=lang, defaults={"value": value}
            )
            self._mem[f"{lang}:{key}"] = value
        except Exception as e:
            logger.warning("ORM i18n set failed for %r/%s: %s", key, lang, e)

    def delete(self, key: str, lang: str | None = None) -> None:
        Model = self._ensure_model()
        try:
            qs = Model.objects.filter(key=key)
            if lang is not None:
                qs = qs.filter(lang=lang)
            qs.delete()
            # 清缓存
            if lang:
                self._mem.pop(f"{lang}:{key}", None)
            else:
                self._mem = {
                    k: v for k, v in self._mem.items() if not k.endswith(f":{key}")
                }
        except Exception as e:
            logger.warning("ORM i18n delete failed: %s", e)

    def get_many(self, keys: Iterable[str], lang: str) -> dict[str, str]:
        out = {}
        for k in keys:
            v = self.get(k, lang)
            if v is not None:
                out[k] = v
        return out

    def list_keys(self) -> list[str]:
        Model = self._ensure_model()
        try:
            return list(
                Model.objects.values_list("key", flat=True).distinct()
            )
        except Exception:
            return []

    def stats(self, lang: str) -> dict[str, Any]:
        Model = self._ensure_model()
        try:
            total = Model.objects.values("key").distinct().count()
            translated = (
                Model.objects.filter(lang=lang)
                .values("key")
                .distinct()
                .count()
            )
        except Exception:
            return {"lang": lang, "total_keys": 0, "translated": 0, "missing": 0, "coverage": 0.0}
        missing = total - translated
        return {
            "lang": lang,
            "total_keys": total,
            "translated": translated,
            "missing": missing,
            "coverage": round(translated / total, 4) if total > 0 else 1.0,
        }

    def clear_cache(self) -> None:
        self._mem.clear()
        self._hits = 0
        self._misses = 0


# ============================================================
# 全局单例管理
# ============================================================


_backend: TranslationBackend | None = None
_backend_lock = threading.Lock()


def get_translation_backend() -> TranslationBackend:
    """获取全局翻译后端（懒加载单例）"""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                # 检查 settings 是否指定了 ORMBackend
                backend_path = getattr(settings, "I18N_TRANSLATION_BACKEND", None)
                if backend_path == "orm":
                    _backend = ORMTranslationBackend()
                else:
                    _backend = CacheTranslationBackend()
    return _backend


def reset_translation_backend(backend: TranslationBackend | None = None) -> None:
    """重置全局后端（测试 / 切换后端用）"""
    global _backend
    _backend = backend


# ============================================================
# 便捷 API
# ============================================================


def register_translation(
    lang: str, key: str, value: str, persist: bool = True
) -> None:
    """
    注册一条翻译。

    >>> register_translation("zh-hans", "common.save_success", "保存成功")
    >>> register_translation("en", "common.save_success", "Saved")
    """
    backend = get_translation_backend()
    backend.set(key, lang, value)
    if persist and isinstance(backend, ORMTranslationBackend):
        # ORMBackend.set 本身已持久化
        pass


def unregister_translation(key: str, lang: str | None = None) -> None:
    """删除翻译；lang=None 删除所有语言"""
    get_translation_backend().delete(key, lang)


def get_translation_stats(lang: str) -> dict[str, Any]:
    """翻译完整度统计"""
    return get_translation_backend().stats(lang)
