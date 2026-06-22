"""
企业级基础设施模块
提供 Redis、RabbitMQ、缓存、消息队列等通用功能
"""

__version__ = '2.0.0'
__author__ = 'Django Enterprise Platform'

# 便捷导入
from utils.cache import get_redis
from utils.mq import get_rabbitmq, async_task

__all__ = ['get_redis', 'get_rabbitmq', 'async_task']
