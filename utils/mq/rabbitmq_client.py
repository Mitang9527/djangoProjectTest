"""
RabbitMQ 消息队列管理模块
支持生产者、消费者、延迟队列等
"""
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import pika
    from pika.exceptions import AMQPConnectionError, ChannelClosed
    HAS_PIKA = True
except ImportError:
    HAS_PIKA = False
    logger.warning("pika 模块未安装，请运行 pip install pika")


class RabbitMQManager:
    """RabbitMQ 管理器"""
    
    def __init__(self):
        if not HAS_PIKA:
            raise ImportError("请先安装 pika 库: pip install pika")
        
        self.config = getattr(settings, 'RABBITMQ_CONFIG', {
            'host': 'localhost',
            'port': 5672,
            'username': 'guest',
            'password': 'guest',
            'virtual_host': '/',
            'heartbeat': 300,
            'connection_attempts': 3,
            'retry_delay': 5,
        })
        self.connection = None
        self.channel = None
        self._connect()
    
    def _connect(self):
        """建立连接"""
        try:
            credentials = pika.PlainCredentials(
                self.config['username'], 
                self.config['password']
            )
            parameters = pika.ConnectionParameters(
                host=self.config['host'],
                port=self.config['port'],
                virtual_host=self.config['virtual_host'],
                credentials=credentials,
                heartbeat=self.config['heartbeat'],
                connection_attempts=self.config['connection_attempts'],
                retry_delay=self.config['retry_delay'],
            )
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            logger.info("RabbitMQ 连接成功")
        except AMQPConnectionError as e:
            logger.error(f"RabbitMQ 连接失败: {str(e)}")
            raise
    
    def _ensure_connection(self):
        """确保连接可用"""
        if not self.connection or self.connection.is_closed:
            self._connect()
        if not self.channel or self.channel.is_closed:
            self.channel = self.connection.channel()
    
    def declare_queue(self, queue_name, durable=True, exclusive=False, auto_delete=False, arguments=None):
        """声明队列"""
        self._ensure_connection()
        self.channel.queue_declare(
            queue=queue_name,
            durable=durable,
            exclusive=exclusive,
            auto_delete=auto_delete,
            arguments=arguments
        )
        logger.debug(f"队列声明成功: {queue_name}")
    
    def declare_exchange(self, exchange_name, exchange_type='direct', durable=True, auto_delete=False):
        """声明交换机"""
        self._ensure_connection()
        self.channel.exchange_declare(
            exchange=exchange_name,
            exchange_type=exchange_type,
            durable=durable,
            auto_delete=auto_delete
        )
        logger.debug(f"交换机声明成功: {exchange_name}")
    
    def bind_queue(self, queue_name, exchange_name, routing_key):
        """绑定队列到交换机"""
        self._ensure_connection()
        self.channel.queue_bind(
            queue=queue_name,
            exchange=exchange_name,
            routing_key=routing_key
        )
        logger.debug(f"队列绑定成功: {queue_name} -> {exchange_name} ({routing_key})")
    
    # ========== 生产者方法 ==========
    
    def publish(self, exchange, routing_key, message, persistent=True):
        """
        发布消息
        
        Args:
            exchange: 交换机名称
            routing_key: 路由键
            message: 消息内容（字典或字符串）
            persistent: 是否持久化
        """
        self._ensure_connection()
        
        properties = pika.BasicProperties(
            delivery_mode=2 if persistent else 1,
            content_type='application/json'
        )
        
        if isinstance(message, (dict, list)):
            message = json.dumps(message, ensure_ascii=False)
        
        try:
            self.channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key,
                body=message,
                properties=properties
            )
            logger.debug(f"消息发布成功: {exchange} -> {routing_key}")
        except Exception as e:
            logger.error(f"消息发布失败: {str(e)}")
            raise
    
    def send_to_queue(self, queue_name, message, persistent=True):
        """直接发送到队列（不经过交换机）"""
        self.declare_queue(queue_name, durable=persistent)
        self.publish('', queue_name, message, persistent=persistent)
    
    # ========== 消费者方法 ==========
    
    def consume(self, queue_name, callback, auto_ack=False):
        """
        开始消费
        
        Args:
            queue_name: 队列名称
            callback: 回调函数
            auto_ack: 是否自动确认
        """
        self._ensure_connection()
        self.declare_queue(queue_name)
        
        def on_message_callback(ch, method, properties, body):
            try:
                message = json.loads(body.decode('utf-8'))
                callback(message)
                if not auto_ack:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"消息处理失败: {str(e)}")
                if not auto_ack:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        
        self.channel.basic_consume(
            queue=queue_name,
            on_message_callback=on_message_callback,
            auto_ack=auto_ack
        )
        logger.info(f"开始消费队列: {queue_name}")
        
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            self.channel.stop_consuming()
            logger.info("消费已停止")
    
    def get_one_message(self, queue_name, auto_ack=False):
        """获取一条消息（非阻塞）"""
        self._ensure_connection()
        method_frame, header_frame, body = self.channel.basic_get(queue=queue_name, auto_ack=auto_ack)
        if method_frame:
            if not auto_ack:
                self.channel.basic_ack(delivery_tag=method_frame.delivery_tag)
            return json.loads(body.decode('utf-8'))
        return None
    
    # ========== 高级特性 ==========
    
    def declare_delay_queue(self, queue_name, delay_queue_name, delay_seconds=30):
        """声明延迟队列（使用死信实现）"""
        self._ensure_connection()
        
        # 1. 声明正常队列（带死信配置）
        self.declare_queue(
            queue_name,
            arguments={
                'x-dead-letter-exchange': '',
                'x-dead-letter-routing-key': delay_queue_name,
                'x-message-ttl': delay_seconds * 1000,
            }
        )
        
        # 2. 声明延迟队列（实际处理队列）
        self.declare_queue(delay_queue_name)
        logger.debug(f"延迟队列声明成功: {queue_name} -> {delay_queue_name} (延迟 {delay_seconds}s)")
    
    def publish_delayed(self, queue_name, message, delay_seconds=30):
        """发送延迟消息"""
        delay_queue_name = f"{queue_name}_delay"
        self.declare_delay_queue(queue_name, delay_queue_name, delay_seconds)
        self.send_to_queue(queue_name, message)
    
    def close(self):
        """关闭连接"""
        if self.channel and self.channel.is_open:
            self.channel.close()
        if self.connection and self.connection.is_open:
            self.connection.close()
        logger.info("RabbitMQ 连接已关闭")


# 全局单例工厂
_rabbit_manager = None

def get_rabbitmq():
    """获取 RabbitMQ 管理器实例"""
    global _rabbit_manager
    if not _rabbit_manager:
        _rabbit_manager = RabbitMQManager()
    return _rabbit_manager


# 简单的装饰器，用于异步任务
def async_task(queue_name='default_tasks'):
    """异步任务装饰器（生产者模式）"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                mq = get_rabbitmq()
                task_info = {
                    'task': func.__name__,
                    'module': func.__module__,
                    'args': args,
                    'kwargs': kwargs,
                }
                mq.send_to_queue(queue_name, task_info)
                logger.info(f"任务已发送: {func.__name__}")
                return task_info
            except Exception as e:
                logger.error(f"任务发送失败: {str(e)}")
                return None
        return wrapper
    return decorator
