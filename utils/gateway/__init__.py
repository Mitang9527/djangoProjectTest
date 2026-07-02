"""
API 网关 & 可配置限流模块
=========================

架构：
  GatewayMiddleware   → 请求入口，限流头注入，429 拦截
  ConfigurableThrottle → DRF BaseThrottle 子类，Redis 滑动窗口
  APILimitRule        → 路由级限流规则模型
  TenantConfig/PlanFeature → 租户/套餐级限流配置

用法：
  from utils.gateway import (
      IPThrottle, UserThrottle, TenantThrottle, EndpointThrottle,
      GatewayMiddleware, get_gateway_config,
  )
"""

from .throttle import (
    IPThrottle,
    UserThrottle,
    TenantThrottle,
    EndpointThrottle,
    ConfigurableRateThrottle,
    parse_rate,
    get_gateway_config,
    check_sliding_window,
)
from .middleware import GatewayMiddleware

__all__ = [
    "IPThrottle",
    "UserThrottle",
    "TenantThrottle",
    "EndpointThrottle",
    "ConfigurableRateThrottle",
    "GatewayMiddleware",
    "parse_rate",
    "get_gateway_config",
    "check_sliding_window",
]
