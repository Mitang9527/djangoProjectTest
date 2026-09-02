"""
API 签名验证核心功能
"""

import hmac
import hashlib
import json
import time
import secrets
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode, parse_qsl
from django.conf import settings
from loguru import logger

from .exceptions import (
    InvalidSignatureError,
    SignatureExpiredError,
    NonceUsedError,
    MissingHeaderError,
)


# ==================== 配置常量 ====================
# 以下为兜底默认值：当 settings 中未配置对应项时生效。
# 正式配置请在 settings（base.py）中通过 API_TIMESTAMP_TOLERANCE / API_NONCE_TTL 设定，
# 二者为唯一权威来源，运行时由 _resolve_* 解析。
DEFAULT_TIMESTAMP_TOLERANCE = 300  # 兜底：时间容忍度 5分钟
DEFAULT_NONCE_TTL = 600  # 兜底：nonce 有效期 10分钟


def _resolve_timestamp_tolerance(value: Optional[int]) -> int:
    """解析时间戳容忍度：显式值优先，否则读 settings.API_TIMESTAMP_TOLERANCE，兜底 DEFAULT。"""
    if value is not None:
        return value
    return getattr(settings, 'API_TIMESTAMP_TOLERANCE', DEFAULT_TIMESTAMP_TOLERANCE)


def _resolve_nonce_ttl(value: Optional[int]) -> int:
    """解析 nonce 有效期：显式值优先，否则读 settings.API_NONCE_TTL，兜底 DEFAULT。"""
    if value is not None:
        return value
    return getattr(settings, 'API_NONCE_TTL', DEFAULT_NONCE_TTL)


# ==================== Redis 存储后端 ====================
class NonceStore:
    """Nonce 存储后端抽象"""

    def store(self, nonce: str, timestamp: int, ttl: int) -> bool:
        """
        存储 nonce，如果已存在返回 False

        Args:
            nonce: 唯一标识
            timestamp: 时间戳
            ttl: 过期时间（秒）

        Returns:
            bool: True 表示存储成功，False 表示已存在
        """
        raise NotImplementedError

    def exists(self, nonce: str) -> bool:
        """检查 nonce 是否存在"""
        raise NotImplementedError


class RedisNonceStore(NonceStore):
    """基于 Redis 的 nonce 存储"""

    def __init__(self, redis_client=None):
        self._redis_client = redis_client
        self._key_prefix = "api_nonce:"

    def _get_redis(self):
        if self._redis_client is None:
            from framework.cache.redis_client import get_redis
            self._redis_client = get_redis()
        return self._redis_client

    def store(self, nonce: str, timestamp: int, ttl: int) -> bool:
        try:
            redis = self._get_redis()
            key = f"{self._key_prefix}{nonce}"
            # 使用 SETNX 原子操作
            result = redis.set(key, str(timestamp), ex=ttl, nx=True)
            return result is True
        except Exception as e:
            logger.warning(f"Redis nonce store error: {e}")
            # 如果 Redis 不可用，降级为允许通过
            return True

    def exists(self, nonce: str) -> bool:
        try:
            redis = self._get_redis()
            key = f"{self._key_prefix}{nonce}"
            return redis.exists(key) > 0
        except Exception as e:
            logger.warning(f"Redis nonce exists error: {e}")
            return False


class MemoryNonceStore(NonceStore):
    """基于内存的 nonce 存储（仅用于开发/测试）"""

    def __init__(self):
        import threading
        self._store = {}
        self._lock = threading.Lock()

    def store(self, nonce: str, timestamp: int, ttl: int) -> bool:
        with self._lock:
            if nonce in self._store:
                return False
            self._store[nonce] = (timestamp, time.time() + ttl)
            return True

    def exists(self, nonce: str) -> bool:
        with self._lock:
            if nonce not in self._store:
                return False
            # 检查是否过期
            _, expire_at = self._store[nonce]
            if time.time() > expire_at:
                del self._store[nonce]
                return False
            return True


# ==================== 签名生成与验证 ====================
def generate_signature(
    secret_key: str,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    timestamp: Optional[int] = None,
    nonce: Optional[str] = None,
) -> Tuple[str, int, str]:
    """
    生成 API 签名

    Args:
        secret_key: 密钥
        method: HTTP 方法（GET/POST/PUT/DELETE 等）
        path: 请求路径
        params: URL 查询参数
        body: 请求体（JSON）
        timestamp: 时间戳（可选，默认当前时间）
        nonce: 随机字符串（可选，默认生成）

    Returns:
        Tuple (signature, timestamp, nonce)
    """
    timestamp = timestamp or int(time.time())
    nonce = nonce or secrets.token_hex(16)

    # 构建签名字符串
    signature_parts = []

    # 1. HTTP 方法（大写）
    signature_parts.append(method.upper())

    # 2. 请求路径
    signature_parts.append(path)

    # 3. 查询参数（排序后）
    if params:
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        signature_parts.append(urlencode(sorted_params))
    else:
        signature_parts.append("")

    # 4. 请求体（如果有）
    if body:
        # 确保 JSON 格式一致（排序键）
        body_str = json.dumps(body, sort_keys=True, separators=(",", ":"))
        signature_parts.append(body_str)
    else:
        signature_parts.append("")

    # 5. 时间戳
    signature_parts.append(str(timestamp))

    # 6. nonce
    signature_parts.append(nonce)

    # 拼接签名字符串
    signature_string = "|".join(signature_parts)

    # 计算 HMAC-SHA256
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signature_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature, timestamp, nonce


def verify_signature(
    signature: str,
    secret_key: str,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    timestamp: int = 0,
    nonce: str = "",
    timestamp_tolerance: int = None,
) -> bool:
    """
    验证 API 签名

    Args:
        signature: 待验证的签名
        secret_key: 密钥
        method: HTTP 方法
        path: 请求路径
        params: URL 查询参数
        body: 请求体
        timestamp: 时间戳
        nonce: 随机字符串
        timestamp_tolerance: 时间戳容忍度（秒）

    Returns:
        bool: 验证是否通过

    Raises:
        SignatureExpiredError: 签名已过期
        InvalidSignatureError: 签名无效
    """
    timestamp_tolerance = _resolve_timestamp_tolerance(timestamp_tolerance)

    # 检查时间戳
    current_time = int(time.time())
    if abs(current_time - timestamp) > timestamp_tolerance:
        raise SignatureExpiredError(f"签名已过期（时间戳偏差超过 {timestamp_tolerance} 秒）")

    # 重新计算签名进行比对
    expected_signature, _, _ = generate_signature(
        secret_key=secret_key,
        method=method,
        path=path,
        params=params,
        body=body,
        timestamp=timestamp,
        nonce=nonce,
    )

    # 防止时序攻击，使用安全比较
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidSignatureError("签名无效")

    return True


# ==================== 签名验证器 ====================
class SignatureVerifier:
    """API 签名验证器"""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        timestamp_tolerance: int = None,
        nonce_ttl: int = None,
        nonce_store: Optional[NonceStore] = None,
    ):
        """
        初始化签名验证器

        Args:
            secret_key: 密钥（如果为 None，从 settings.API_SECRET_KEY 读取）
            timestamp_tolerance: 时间戳容忍度（秒）
            nonce_ttl: nonce 有效期（秒）
            nonce_store: nonce 存储后端（如果为 None，自动选择）
        """
        self.secret_key = secret_key or getattr(settings, 'API_SECRET_KEY', '')
        self.timestamp_tolerance = _resolve_timestamp_tolerance(timestamp_tolerance)
        self.nonce_ttl = _resolve_nonce_ttl(nonce_ttl)

        # 初始化 nonce 存储
        if nonce_store is not None:
            self.nonce_store = nonce_store
        else:
            # 尝试使用 Redis，回退到内存
            try:
                self.nonce_store = RedisNonceStore()
            except Exception:
                self.nonce_store = MemoryNonceStore()

    def verify_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        signature: str = "",
        timestamp: int = 0,
        nonce: str = "",
        access_key: Optional[str] = None,
    ) -> bool:
        """
        验证请求

        Args:
            method: HTTP 方法
            path: 请求路径
            params: URL 查询参数
            body: 请求体
            signature: 签名
            timestamp: 时间戳
            nonce: 随机字符串
            access_key: 访问密钥（可选，用于多租户场景）

        Returns:
            bool: 验证是否通过

        Raises:
            MissingHeaderError: 缺少必要参数
            NonceUsedError: nonce 已被使用
            SignatureExpiredError: 签名已过期
            InvalidSignatureError: 签名无效
        """
        # 检查必要参数
        if not signature:
            raise MissingHeaderError("缺少签名参数")
        if not timestamp:
            raise MissingHeaderError("缺少时间戳参数")
        if not nonce:
            raise MissingHeaderError("缺少 nonce 参数")

        # 检查 nonce 是否已被使用
        if not self.nonce_store.store(nonce, timestamp, self.nonce_ttl):
            raise NonceUsedError("nonce 已被使用")

        # 获取密钥（支持多 access_key）
        secret_key = self._get_secret_key(access_key)
        if not secret_key:
            raise InvalidSignatureError("无效的 access_key")

        verify_signature(
            signature=signature,
            secret_key=secret_key,
            method=method,
            path=path,
            params=params,
            body=body,
            timestamp=timestamp,
            nonce=nonce,
            timestamp_tolerance=self.timestamp_tolerance,
        )

        return True

    def _get_secret_key(self, access_key: Optional[str]) -> str:
        """
        获取密钥（支持多 access_key 配置）

        Args:
            access_key: 访问密钥

        Returns:
            str: 密钥
        """
        if not access_key:
            return self.secret_key

        # 支持多密钥配置
        api_keys = getattr(settings, 'API_ACCESS_KEYS', {})
        return api_keys.get(access_key, self.secret_key)
