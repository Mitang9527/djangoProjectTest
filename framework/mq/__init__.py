"""
队列工具包
包含 RabbitMQ、消息队列相关功能
"""
from .rabbitmq_client import (
    get_rabbitmq,
    RabbitMQManager,
    async_task,
)

__all__ = ['get_rabbitmq', 'RabbitMQManager', 'async_task']
