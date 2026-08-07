"""
企业级基础设施模块
提供 Redis、缓存等通用功能
"""

__version__ = '2.0.0'
__author__ = 'Django Enterprise Platform'

# 便捷导入
from framework.cache import get_redis

__all__ = ['get_redis']
