"""
企业级基础设施使用示例
包含 Redis、RabbitMQ 等模块的使用方法
"""

# =====================================================
# Redis 使用示例
# =====================================================

def redis_example():
    """Redis 缓存使用示例"""
    from utils.cache.redis_client import get_redis
    
    redis = get_redis()
    
    # --- 基础操作 ---
    # 设置键值
    redis.set('user:1', {'name': '张三', 'age': 25}, ex=3600)  # 1小时过期
    
    # 获取值
    user = redis.get('user:1')
    print(f"用户信息: {user}")
    
    # 检查键是否存在
    if redis.exists('user:1'):
        print("用户数据存在")
    
    # 获取剩余过期时间
    ttl = redis.ttl('user:1')
    print(f"剩余时间: {ttl}秒")
    
    # 删除键
    # redis.delete('user:1')
    
    # --- 计数器 ---
    redis.set('views', 0)
    redis.incr('views')
    views = redis.get('views')
    print(f"访问次数: {views}")
    
    # --- Hash 操作 ---
    redis.hset('config', 'site_title', '企业级平台')
    redis.hset('config', 'version', '2.0.0')
    config = redis.hget('config', 'site_title')
    all_config = redis.hgetall('config')
    print(f"网站标题: {config}")
    print(f"所有配置: {all_config}")
    
    # --- List 队列 ---
    redis.lpush('task_queue', {'task_id': 1, 'data': '发送邮件'})
    task = redis.rpop('task_queue')
    print(f"处理任务: {task}")
    
    print("Redis 操作示例完成")


# =====================================================
# RabbitMQ 使用示例
# =====================================================

def rabbitmq_producer_example():
    """RabbitMQ 生产者示例"""
    from utils.mq.rabbitmq_client import get_rabbitmq
    
    mq = get_rabbitmq()
    
    # --- 直接发送到队列 ---
    mq.send_to_queue('email_tasks', {
        'to': 'user@example.com',
        'subject': '通知邮件',
        'content': '这是一封测试邮件',
    })
    
    # --- 使用交换机 ---
    mq.declare_exchange('notification_exchange', 'direct')
    mq.declare_queue('sms_tasks')
    mq.bind_queue('sms_tasks', 'notification_exchange', 'sms')
    
    mq.publish(
        exchange='notification_exchange',
        routing_key='sms',
        message={
            'phone': '13800138000',
            'content': '这是一条短信通知',
        }
    )
    
    # --- 延迟消息 ---
    mq.publish_delayed(
        'order_cancel',
        {
            'order_id': 'ORD12345',
            'reason': '超时未支付',
        },
        delay_seconds=60  # 60秒后处理
    )
    
    print("RabbitMQ 生产者示例完成")


def rabbitmq_consumer_example():
    """RabbitMQ 消费者示例（需要在独立进程运行）"""
    from utils.mq.rabbitmq_client import get_rabbitmq
    
    def process_email_task(message):
        print(f"收到邮件任务: {message}")
        # 实际的邮件发送逻辑写在这里
    
    mq = get_rabbitmq()
    mq.consume('email_tasks', process_email_task, auto_ack=False)


# =====================================================
# 异步任务装饰器示例
# =====================================================

def async_task_example():
    """异步任务装饰器使用示例"""
    from utils.mq.rabbitmq_client import async_task
    
    @async_task(queue_name='email_tasks')
    def send_email(to, subject, content):
        """发送邮件的耗时任务"""
        # 这里是耗时的邮件发送逻辑
        print(f"发送邮件给: {to}, 主题: {subject}")
        return True
    
    # 使用方式
    result = send_email(
        to='user@example.com',
        subject='测试邮件',
        content='这是测试内容'
    )
    print(f"异步任务已发送: {result}")


# =====================================================
# 实际业务场景示例 - 集成到 Django View
# =====================================================

def django_view_example():
    """在 Django View 中使用的示例"""
    from rest_framework.views import APIView
    from rest_framework.response import Response
    from utils.cache.redis_client import get_redis
    
    class UserProfileView(APIView):
        """用户详情视图（带缓存）"""
        
        def get(self, request, user_id):
            redis = get_redis()
            cache_key = f'user_profile:{user_id}'
            
            # 1. 先查缓存
            profile = redis.get(cache_key)
            
            if not profile:
                # 2. 缓存未命中，查数据库
                # profile = User.objects.get(id=user_id)
                profile = {'id': user_id, 'name': '示例用户', 'email': 'test@example.com'}
                
                # 3. 写入缓存
                redis.set(cache_key, profile, ex=3600)
            
            return Response(profile)


# =====================================================
# 分布式锁示例
# =====================================================

def redis_lock_example():
    """Redis 分布式锁示例（防止并发问题）"""
    from utils.cache.redis_client import get_redis
    import time
    
    redis = get_redis()
    lock_key = 'resource:1:lock'
    
    # 尝试获取锁
    if redis.set(lock_key, 'locked', nx=True, ex=30):  # 30秒超时
        try:
            print("获取锁成功，执行任务...")
            # 执行临界区代码
            time.sleep(5)
        finally:
            # 释放锁
            redis.delete(lock_key)
            print("任务完成，释放锁")
    else:
        print("获取锁失败，资源正被占用")


if __name__ == '__main__':
    print("=== 企业级基础设施使用示例 ===")
    
    # 运行示例
    try:
        redis_example()
        rabbitmq_producer_example()
        async_task_example()
        redis_lock_example()
    except Exception as e:
        print(f"示例运行可能需要先安装依赖或启动服务: {e}")
        print("\n提示:")
        print("1. 安装依赖: pip install redis pika")
        print("2. 启动 Redis 服务")
        print("3. 启动 RabbitMQ 服务 (可选)")
