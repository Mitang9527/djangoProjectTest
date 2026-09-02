"""
API 网关限流引擎：基于 Redis 滑动窗口（Sorted Set）的可配置限流器。

限流器类型：IPThrottle(客户端IP)、UserThrottle(认证用户ID)、AnonThrottle(匿名IP，
登录用户放行)、TenantThrottle(租户ID)、EndpointThrottle(URL路由+用户/IP组合)。

配置优先级（高→低）：APILimitRule(路由级) > PlanFeature(套餐级) > TenantConfig(租户级) > 全局默认。

滑动窗口算法：ZREMRANGEBYSCORE 清理过期 → ZCARD 计数 → count>=limit 拒绝(429) →
ZADD 记录当前请求 → EXPIRE 设置 key 过期。
"""

import re
import time
from functools import lru_cache
from typing import Optional, Tuple
from datetime import datetime, timedelta
from threading import Lock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from loguru import logger
from rest_framework.throttling import BaseThrottle

from framework.cache.redis_client import get_redis


# 全局默认限流值（延迟读取，导入时若 Django 未就绪则使用默认值）
try:
    DEFAULT_THROTTLE_RATES = getattr(settings, "GATEWAY_THROTTLE_RATES", {
        "ip":       "1000/h",
        "user":     "500/h",
        "tenant":   "10000/h",
        "anon":     "60/m",
    })
except ImproperlyConfigured:
    # Django 未完全初始化时导入本模块，使用默认值；
    # 运行时通过 get_gateway_config 读取配置（此时 settings 已就绪）
    DEFAULT_THROTTLE_RATES = {
        "ip":       "1000/h",
        "user":     "500/h",
        "tenant":   "10000/h",
        "anon":     "60/m",
    }

# 限流 Redis 键前缀
REDIS_KEY_PREFIX = "ratelimit:gw:"

# 时间单位 → 秒
_TIME_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# 规则缓存管理 - 支持实时刷新
class RuleCacheManager:
    """限流规则缓存管理器，支持实时刷新"""
    
    _cache = None
    _cache_updated_at = None
    _cache_ttl = 5  # 缓存 5 秒，过期自动刷新
    _lock = Lock()
    _cache_identifier = None
    
    @classmethod
    def _get_cache_identifier(cls):
        """获取缓存版本标识，用于检测规则是否更新"""
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT MAX(updated_at) FROM saas_apilimitrule WHERE is_active = TRUE")
                result = cursor.fetchone()
                if result and result[0]:
                    return str(result[0])
        except Exception:
            pass
        return str(time.time())
    
    @classmethod
    def _load_rules(cls):
        """从数据库加载所有活跃规则"""
        try:
            from system.saas.models import APILimitRule
            rules = list(APILimitRule.objects.filter(is_active=True).order_by('priority', '-created_at'))
            return rules
        except Exception as e:
            logger.warning(f"[Gateway] 加载规则失败: {e}")
            return []
    
    @classmethod
    def get_rules(cls):
        """获取规则（带缓存）"""
        with cls._lock:
            now = time.time()
            
            # 检查缓存是否需要刷新
            if (cls._cache is None or 
                cls._cache_updated_at is None or 
                (now - cls._cache_updated_at) > cls._cache_ttl):
                
                # 检查规则是否有更新
                new_identifier = cls._get_cache_identifier()
                if cls._cache is None or new_identifier != cls._cache_identifier:
                    cls._cache = cls._load_rules()
                    cls._cache_identifier = new_identifier
                    logger.debug(f"[Gateway] 规则缓存已刷新，共 {len(cls._cache)} 条规则")
                cls._cache_updated_at = now
            
            return cls._cache
    
    @classmethod
    def invalidate(cls):
        """主动失效缓存"""
        with cls._lock:
            cls._cache = None
            cls._cache_updated_at = None
            cls._cache_identifier = None
            logger.info("[Gateway] 规则缓存已清除")
    
    @classmethod
    def find_matching_rule(cls, path, throttle_type=None):
        """查找匹配的规则"""
        rules = cls.get_rules()
        
        for rule in rules:
            if throttle_type and rule.throttle_type != throttle_type:
                continue
            
            if rule.matches(path):
                return rule
        
        return None


rule_cache = RuleCacheManager()


# 工具函数

def parse_rate(rate_str: str) -> Tuple[int, int]:
    """解析速率字符串，如 "100/h" → (100, 3600)。

    Args: rate_str 形如 "100/h"/"60/m"/"1000/d"。Returns: (limit, window_seconds)。
    """
    if not rate_str or "/" not in rate_str:
        parsed = _parse_simple_rate(rate_str)
        if parsed:
            return parsed
        return (100, 3600)  # fallback

    parts = rate_str.strip().split("/")
    try:
        limit = int(parts[0])
    except (ValueError, IndexError):
        limit = 100

    unit = parts[1].strip() if len(parts) > 1 else "h"
    window = _TIME_UNITS.get(unit, 3600)

    return (limit, window)


def _parse_simple_rate(rate_str: str) -> Optional[Tuple[int, int]]:
    """解析纯数字速率（已废弃格式兼容）"""
    if not rate_str:
        return None
    try:
        return (int(rate_str), 3600)
    except ValueError:
        return None


def _get_client_ip(request) -> str:
    """从请求中提取真实客户端 IP"""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("HTTP_X_REAL_IP", "")
    if not ip:
        ip = request.META.get("REMOTE_ADDR", "unknown")
    return ip


def _redis_available() -> bool:
    """检查 Redis 是否可用"""
    try:
        client = get_redis()
        client.get_client().ping()
        return True
    except Exception:
        return False


def _redis_fail_open() -> bool:
    """Redis 故障时的限流策略：True=放行(fail-open)，False=拒绝(fail-closed)。

    读取 settings.GATEWAY_THROTTLE_REDIS_FAIL_OPEN（默认 False）。fail-closed 下
    Redis 不可用直接 429，保证限流不因基础设施故障失效；需「降级放行」的环境可显式置 True。
    """
    try:
        return bool(getattr(settings, "GATEWAY_THROTTLE_REDIS_FAIL_OPEN", False))
    except Exception:
        return False


def check_sliding_window(key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
    """Redis 滑动窗口速率检查（ZSET：member=时间戳+随机后缀防重复，score=时间戳）。

    Args: key=Redis 键; limit=窗口内最大请求数; window_seconds=窗口大小（秒）。
    Returns: (allowed, remaining, reset_in_seconds)。
    """
    if not _redis_available():
        # Redis 不可用：默认 fail-closed（拒绝 429）；GATEWAY_THROTTLE_REDIS_FAIL_OPEN=True 时放行
        if _redis_fail_open():
            return (True, limit, window_seconds)
        logger.warning(f"[Gateway] Redis 不可用，限流 fail-closed 拒绝请求 (key={key})")
        return (False, 0, window_seconds)

    try:
        client = get_redis().get_client()
        now = time.time()
        window_start = now - window_seconds

        # 使用 pipeline 保证原子性
        pipe = client.pipeline(transaction=True)
        pipe.zremrangebyscore(key, 0, window_start)   # 1) 清理过期
        pipe.zcard(key)                                  # 2) 当前计数
        pipe.execute()

        count_result = client.zcard(key)
        current_count = int(count_result or 0)

        if current_count >= limit:
            # 计算最早记录的时间，估算重置时间
            earliest = client.zrange(key, 0, 0, withscores=True)
            if earliest:
                reset_in = int(earliest[0][1] + window_seconds - now)
                reset_in = max(1, reset_in)
            else:
                reset_in = window_seconds
            return (False, 0, reset_in)

        # 放行：添加当前请求
        member = f"{now}:{time.perf_counter_ns()}"
        client.zadd(key, {member: now})
        client.expire(key, window_seconds * 2)

        remaining = limit - current_count - 1
        return (True, remaining, window_seconds)

    except Exception as e:
        logger.warning(f"[Gateway] 滑动窗口检查失败 (key={key}): {e}")
        # 与 Redis 不可用保持一致：默认 fail-closed，可配置 fail-open
        if _redis_fail_open():
            return (True, limit, window_seconds)
        return (False, 0, window_seconds)


# 配置管理器

class GatewayConfigManager:
    """网关配置管理器：从多个来源获取限流值。

    优先级：APILimitRule(路由级) > PlanFeature(套餐级) > TenantConfig(租户级) > 全局默认。
    """

    @staticmethod
    def get_rate_for_request(request, throttle_type: str) -> Tuple[int, int]:
        """获取当前请求的速率限制。

        Args: request=Django/DRF 请求对象; throttle_type='ip'|'user'|'tenant'。
        Returns: (limit, window_seconds)。
        """
        path = request.path if hasattr(request, 'path') else ''

        # 1) 路由级规则 (APILimitRule)
        rule_rate = GatewayConfigManager._get_rule_rate(path, throttle_type)
        if rule_rate:
            return rule_rate

        # 2) 套餐级 (PlanFeature)
        plan_rate = GatewayConfigManager._get_plan_rate(request, throttle_type)
        if plan_rate:
            return plan_rate

        # 3) 租户级 (TenantConfig)
        tenant_rate = GatewayConfigManager._get_tenant_config_rate(request, throttle_type)
        if tenant_rate:
            return tenant_rate

        # 4) 全局默认
        default = DEFAULT_THROTTLE_RATES.get(throttle_type, "100/h")
        return parse_rate(default)

    @staticmethod
    def _get_rule_rate(path: str, throttle_type: str) -> Optional[Tuple[int, int]]:
        """从 APILimitRule 表查询"""
        try:
            from system.saas.models import APILimitRule
            rules = APILimitRule.objects.filter(
                is_active=True,
                throttle_type=throttle_type,
            ).order_by("priority")

            for rule in rules:
                if rule.matches(path):
                    return parse_rate(rule.rate) if rule.rate else None
        except Exception:
            pass
        return None

    @staticmethod
    def _get_plan_rate(request, throttle_type: str) -> Optional[Tuple[int, int]]:
        """从 PlanFeature 查询"""
        try:
            tenant = getattr(request, 'tenant', None)
            if not tenant or not tenant.plan_id:
                return None

            from system.saas.models import PlanFeature
            feature_code = f"rate_limit.{throttle_type}"
            feature = PlanFeature.objects.filter(
                plan_id=tenant.plan_id,
                feature_code=feature_code,
                is_enabled=True,
            ).first()
            if feature and feature.value:
                return parse_rate(feature.value)
        except Exception:
            pass
        return None

    @staticmethod
    def _get_tenant_config_rate(request, throttle_type: str) -> Optional[Tuple[int, int]]:
        """从 TenantConfig 查询"""
        try:
            tenant = getattr(request, 'tenant', None)
            if not tenant:
                return None

            from system.saas.models import TenantConfig
            config_key = f"rate_limit.{throttle_type}"
            config = TenantConfig.objects.filter(
                tenant=tenant,
                key=config_key,
            ).first()
            if config and config.value:
                return parse_rate(config.value)
        except Exception:
            pass
        return None


get_gateway_config = GatewayConfigManager()


# DRF 限流器基类

class ConfigurableRateThrottle(BaseThrottle):
    """可配置速率限流器基类。

    子类覆盖 throttle_type（限流类型）与 get_identity(request)（返回限流维度标识：
    IP / user_id / tenant_id）。
    配置来源：全局默认 GATEWAY_THROTTLE_RATES / TenantConfig(rate_limit.{type}) /
    PlanFeature(feature_code=rate_limit.{type}) / APILimitRule 路由规则。
    """

    throttle_type: str = "ip"           # 子类覆盖
    scope: str | None = None            # DRF scope（不使用，由自定义配置替代）
    timer = time.time                    # 可注入时间源
    cache_format = "throttle_%(scope)s_%(ident)s"  # DRF 兼容格式（未使用）

    def __init__(self):
        self._rate_limit: Optional[int] = None
        self._window_seconds: Optional[int] = None
        self._remaining: Optional[int] = None
        self._reset_in: Optional[int] = None

    def allow_request(self, request, view) -> bool:
        """检查是否允许请求：True 放行，False 拒绝并触发 429。"""
        identity = self.get_identity(request)
        if not identity:
            return True

        limit, window = get_gateway_config.get_rate_for_request(request, self.throttle_type)

        # 构建 Redis key
        now = self.timer()
        key = f"{REDIS_KEY_PREFIX}{self.throttle_type}:{identity}"

        # 滑动窗口检查
        allowed, remaining, reset_in = check_sliding_window(key, limit, window)

        # 记录状态（供 wait() 和响应头注入使用）
        self._rate_limit = limit
        self._window_seconds = window
        self._remaining = remaining
        self._reset_in = reset_in

        if not allowed:
            self._throttled_at = now

        request._gateway_throttle_info = {
            "type": self.throttle_type,
            "limit": limit,
            "remaining": remaining,
            "reset_in": reset_in,
            "allowed": allowed,
        }

        return allowed

    def wait(self) -> float:
        """返回需要等待的秒数（429 时 DRF 自动调用）"""
        if self._reset_in:
            return float(self._reset_in)
        return 0.0

    def get_identity(self, request) -> str:
        """获取限流维度标识，子类必须覆盖"""
        raise NotImplementedError("子类必须实现 get_identity()")


# 具体限流器实现

class IPThrottle(ConfigurableRateThrottle):
    """按客户端 IP 限流"""
    throttle_type = "ip"

    def get_identity(self, request) -> str:
        return _get_client_ip(request)


class UserThrottle(ConfigurableRateThrottle):
    """按认证用户限流"""
    throttle_type = "user"

    def get_identity(self, request) -> str:
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            return str(user.pk)
        return ""


class AnonThrottle(ConfigurableRateThrottle):
    """按匿名用户 IP 限流（仅对未登录请求生效）。

    登录用户返回空 identity → allow_request 直接放行，避免与 UserThrottle 叠加
    造成 anon 档（默认 60/m）误杀已登录用户；未登录请求按客户端 IP 限流。
    配置来源同其他限流器，也可用 APILimitRule throttle_type="anon" 路由规则覆盖。
    """
    throttle_type = "anon"

    def get_identity(self, request) -> str:
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            return ""
        return _get_client_ip(request)


class TenantThrottle(ConfigurableRateThrottle):
    """按租户限流"""
    throttle_type = "tenant"

    def get_identity(self, request) -> str:
        tenant = getattr(request, 'tenant', None)
        if tenant:
            return str(tenant.pk)
        # 无租户上下文时降级为 IP
        return f"no-tenant:{_get_client_ip(request)}"


class EndpointThrottle(ConfigurableRateThrottle):
    """按 API 路由限流（路由 + 用户/IP 组合）"""
    throttle_type = "endpoint"

    def get_identity(self, request) -> str:
        path = request.path if hasattr(request, 'path') else ''
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            return f"{path}:user:{user.pk}"
        return f"{path}:ip:{_get_client_ip(request)}"

    def allow_request(self, request, view) -> bool:
        """Endpoint 限流在路由规则中查找匹配"""
        identity = self.get_identity(request)
        if not identity:
            return True

        # 按优先级链取值：路由规则 → PlanFeature → TenantConfig → 全局默认。
        # ⚠️ 规则存在但路径未匹配时不可硬编码回退，否则会跳过套餐/租户/全局配置。
        limit, window = get_gateway_config.get_rate_for_request(request, "endpoint")

        key = f"{REDIS_KEY_PREFIX}endpoint:{identity}"
        allowed, remaining, reset_in = check_sliding_window(key, limit, window)

        self._rate_limit = limit
        self._window_seconds = window
        self._remaining = remaining
        self._reset_in = reset_in

        request._gateway_throttle_info = {
            "type": "endpoint",
            "limit": limit,
            "remaining": remaining,
            "reset_in": reset_in,
            "allowed": allowed,
        }

        return allowed
