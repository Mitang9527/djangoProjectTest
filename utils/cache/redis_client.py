"""
Redis 缓存连接管理模块
支持单节点和 Sentinel 模式
"""
import pickle
import functools
from typing import Optional, Callable, Any
from django.conf import settings
from django.core.cache import cache as django_cache
from loguru import logger

try:
    import redis
    from redis.connection import ConnectionPool
    from redis.exceptions import ConnectionError, TimeoutError
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.warning("Redis 模块未安装，请运行 pip install redis")


class RedisClient:
    """Redis 客户端单例封装"""
    
    _instance = None
    _redis_pool = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not HAS_REDIS:
            raise ImportError("请先安装 redis 库: pip install redis")
            
        if self._redis_pool is None:
            self._init_pool()
    
    def _init_pool(self):
        """初始化 Redis 连接池"""
        redis_config = getattr(settings, 'CACHES', {}).get('default', {})
        
        # 支持从 settings.CACHES 配置或单独的 REDIS_CONFIG 读取
        redis_conf = getattr(settings, 'REDIS_CONFIG', {
            'host': redis_config.get('LOCATION', 'localhost').replace('redis://', ''),
            'port': 6379,
            'db': 0,
            'password': None,
            'max_connections': 100,
            'socket_connect_timeout': 5,
            'socket_timeout': 10,
        })
        
        try:
            if isinstance(redis_conf['host'], str) and 'sentinel' in redis_conf['host'].lower():
                # Sentinel 模式
                self._init_sentinel(redis_conf)
            else:
                # 单节点模式
                self._redis_pool = ConnectionPool(
                    host=redis_conf.get('host', 'localhost'),
                    port=redis_conf.get('port', 6379),
                    db=redis_conf.get('db', 0),
                    password=redis_conf.get('password'),
                    max_connections=redis_conf.get('max_connections', 100),
                    socket_connect_timeout=redis_conf.get('socket_connect_timeout', 5),
                    socket_timeout=redis_conf.get('socket_timeout', 10),
                    decode_responses=False,  # 默认不自动解码，支持 pickle 序列化
                )
            logger.info("Redis 连接池初始化成功")
        except Exception as e:
            logger.error(f"Redis 连接池初始化失败: {str(e)}")
            raise
    
    def _init_sentinel(self, config):
        """Sentinel 模式初始化（占位）"""
        logger.warning("Sentinel 模式尚未完全实现，当前使用单节点模式")
        self._redis_pool = ConnectionPool(
            host=config.get('host', 'localhost'),
            port=config.get('port', 6379),
            db=config.get('db', 0),
            password=config.get('password'),
        )
    
    def get_client(self):
        """获取 Redis 客户端实例"""
        if not self._redis_pool:
            self._init_pool()
        return redis.Redis(connection_pool=self._redis_pool)
    
    # ========== 基础操作封装 ==========
    
    def set(self, key, value, ex=None, px=None, nx=False, xx=False):
        """设置键值对"""
        try:
            client = self.get_client()
            # 序列化复杂对象
            serialized_value = pickle.dumps(value)
            return client.set(key, serialized_value, ex=ex, px=px, nx=nx, xx=xx)
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis set 操作失败: {str(e)}")
            return False
    
    def get(self, key, default=None):
        """获取值"""
        try:
            client = self.get_client()
            value = client.get(key)
            if value is None:
                return default
            return pickle.loads(value)
        except Exception as e:
            logger.error(f"Redis get 操作失败: {str(e)}")
            return default
    
    def delete(self, *keys):
        """删除键"""
        try:
            client = self.get_client()
            return client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis delete 操作失败: {str(e)}")
            return 0
    
    def exists(self, key):
        """检查键是否存在"""
        try:
            client = self.get_client()
            return client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis exists 操作失败: {str(e)}")
            return False
    
    def expire(self, key, time):
        """设置过期时间"""
        try:
            client = self.get_client()
            return client.expire(key, time)
        except Exception as e:
            logger.error(f"Redis expire 操作失败: {str(e)}")
            return False
    
    def ttl(self, key):
        """获取剩余过期时间"""
        try:
            client = self.get_client()
            return client.ttl(key)
        except Exception as e:
            logger.error(f"Redis ttl 操作失败: {str(e)}")
            return -1
    
    # ========== 高级操作 ==========
    
    def incr(self, key, amount=1):
        """原子增加"""
        try:
            client = self.get_client()
            return client.incr(key, amount)
        except Exception as e:
            logger.error(f"Redis incr 操作失败: {str(e)}")
            return 0
    
    def decr(self, key, amount=1):
        """原子减少"""
        try:
            client = self.get_client()
            return client.decr(key, amount)
        except Exception as e:
            logger.error(f"Redis decr 操作失败: {str(e)}")
            return 0
    
    def hset(self, name, key, value):
        """Hash 集合设置"""
        try:
            client = self.get_client()
            serialized_value = pickle.dumps(value)
            return client.hset(name, key, serialized_value)
        except Exception as e:
            logger.error(f"Redis hset 操作失败: {str(e)}")
            return 0
    
    def hget(self, name, key, default=None):
        """Hash 集合获取"""
        try:
            client = self.get_client()
            value = client.hget(name, key)
            if value is None:
                return default
            return pickle.loads(value)
        except Exception as e:
            logger.error(f"Redis hget 操作失败: {str(e)}")
            return default
    
    def hgetall(self, name):
        """获取整个 Hash 集合"""
        try:
            client = self.get_client()
            result = {}
            data = client.hgetall(name)
            for k, v in data.items():
                result[k.decode()] = pickle.loads(v)
            return result
        except Exception as e:
            logger.error(f"Redis hgetall 操作失败: {str(e)}")
            return {}
    
    def lpush(self, name, *values):
        """列表左推"""
        try:
            client = self.get_client()
            serialized = [pickle.dumps(v) for v in values]
            return client.lpush(name, *serialized)
        except Exception as e:
            logger.error(f"Redis lpush 操作失败: {str(e)}")
            return 0
    
    def rpop(self, name):
        """列表右弹出"""
        try:
            client = self.get_client()
            value = client.rpop(name)
            return pickle.loads(value) if value else None
        except Exception as e:
            logger.error(f"Redis rpop 操作失败: {str(e)}")
            return None
    
    def llen(self, name):
        """获取列表长度"""
        try:
            client = self.get_client()
            return client.llen(name)
        except Exception as e:
            logger.error(f"Redis llen 操作失败: {str(e)}")
            return 0
    
    def keys(self, pattern='*'):
        """
        模糊匹配键（已迁移到 SCAN，生产安全）

        遗留兼容接口，实际使用 SCAN 迭代。
        """
        try:
            client = self.get_client()
            result = []
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=100)
                result.extend([k.decode() if isinstance(k, bytes) else k for k in keys])
                if cursor == 0:
                    break
            return result
        except Exception as e:
            logger.error(f"Redis scan 操作失败: {str(e)}")
            return []

    def scan_iter(self, pattern: str = '*', count: int = 100):
        """
        SCAN 迭代器（推荐生产环境使用）

        Yields:
            匹配的键名（已解码为字符串）
        """
        try:
            client = self.get_client()
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=count)
                for k in keys:
                    yield k.decode() if isinstance(k, bytes) else k
                if cursor == 0:
                    break
        except Exception as e:
            logger.error(f"Redis scan_iter 操作失败: {str(e)}")


# 全局单例
_redis_client = None

def get_redis():
    """获取 Redis 客户端实例（工厂方法）"""
    global _redis_client
    if not _redis_client:
        _redis_client = RedisClient()
    return _redis_client

def get_cache():
    """获取 Django 原生 Cache 对象（兼容方式）"""
    return django_cache


def redis_cache(
    key_prefix: str = "cache",
    ttl: int = 3600,
    key_func: Optional[Callable] = None,
):
    """
    Redis 缓存装饰器
    
    Args:
        key_prefix: 缓存键前缀
        ttl: 缓存过期时间（秒）
        key_func: 自定义键生成函数（参数为 *args, **kwargs）
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 生成缓存键
            if key_func:
                key = f"{key_prefix}:{key_func(*args, **kwargs)}"
            else:
                # 默认键生成方式：func_name + sorted(args/kwargs)
                sorted_kwargs = sorted(kwargs.items())
                key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(sorted_kwargs)}"
            
            # 尝试获取缓存
            try:
                redis_client = get_redis()
                cached_value = redis_client.get(key)
                
                if cached_value is not None:
                    logger.debug(f"缓存命中: {key}")
                    return cached_value
            except Exception as e:
                logger.warning(f"Redis 缓存读取失败: {e}，回退到直接执行函数")
            
            # 缓存未命中或读取失败，执行原函数
            result = func(*args, **kwargs)
            
            # 尝试写入缓存
            try:
                redis_client.set(key, result, ex=ttl)
                logger.debug(f"缓存已写入: {key}")
            except Exception as e:
                logger.warning(f"Redis 缓存写入失败: {e}")
            
            return result
        return wrapper
    return decorator


def clear_redis_cache(key_pattern: str):
    """
    清除指定模式的 Redis 缓存
    
    Args:
        key_pattern: 键模式（如 "cache:myfunc:*"）
    """
    try:
        redis_client = get_redis()
        keys = redis_client.keys(key_pattern)
        
        if keys:
            deleted_count = redis_client.delete(*keys)
            logger.info(f"已清除 {deleted_count} 个缓存键: {key_pattern}")
            return deleted_count
        else:
            logger.info(f"没有匹配的缓存键: {key_pattern}")
            return 0
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        return 0
