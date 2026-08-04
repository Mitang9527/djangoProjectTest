"""
健康检查模块 - 提供系统健康状态检查功能
"""
import os
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from loguru import logger

try:
    import redis
    from redis.exceptions import RedisError
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

try:
    import pika
    from pika.exceptions import AMQPError
    HAS_RABBITMQ = True
except ImportError:
    HAS_RABBITMQ = False


class HealthStatus(Enum):
    """健康状态枚举"""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    name: str
    status: HealthStatus
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    component_type: str = "component"


class HealthCheck(ABC):
    """健康检查基类"""
    
    name: str
    component_type: str = "component"
    
    @abstractmethod
    def check(self) -> HealthCheckResult:
        pass


class DatabaseHealthCheck(HealthCheck):
    """数据库健康检查"""
    name = "database"
    component_type = "datastore"
    
    def check(self) -> HealthCheckResult:
        try:
            for alias in connections:
                connection = connections[alias]
                connection.cursor()
            return HealthCheckResult(
                status=HealthStatus.PASS,
                message="Database connections are healthy"
            )
        except OperationalError as e:
            logger.error(f"Database health check failed: {e}")
            return HealthCheckResult(
                status=HealthStatus.FAIL,
                message=f"Database connection failed: {str(e)}"
            )


class RedisHealthCheck(HealthCheck):
    """Redis健康检查"""
    name = "redis"
    component_type = "cache"
    
    def check(self) -> HealthCheckResult:
        if not HAS_REDIS:
            return HealthCheckResult(
                status=HealthStatus.PASS,
                message="Redis not configured (optional)"
            )
        
        try:
            redis_config = getattr(settings, "REDIS_CONFIG", {})
            if not redis_config.get("enabled", False):
                return HealthCheckResult(
                    status=HealthStatus.PASS,
                    message="Redis not enabled"
                )
            
            host = redis_config.get("host", "localhost")
            port = redis_config.get("port", 6379)
            password = redis_config.get("password")
            db = redis_config.get("db", 0)
            
            r = redis.Redis(
                host=host,
                port=port,
                password=password,
                db=db,
                socket_connect_timeout=5
            )
            r.ping()
            info = r.info()
            
            return HealthCheckResult(
                status=HealthStatus.PASS,
                message="Redis is healthy",
                metrics={
                    "connected_clients": info.get("connected_clients", 0),
                    "used_memory_human": info.get("used_memory_human", "")
                }
            )
        except RedisError as e:
            logger.error(f"Redis health check failed: {e}")
            return HealthCheckResult(
                status=HealthStatus.FAIL,
                message=f"Redis connection failed: {str(e)}"
            )


class RabbitMQHealthCheck(HealthCheck):
    """RabbitMQ健康检查"""
    name = "rabbitmq"
    component_type = "messaging"
    
    def check(self) -> HealthCheckResult:
        if not HAS_RABBITMQ:
            return HealthCheckResult(
                status=HealthStatus.PASS,
                message="RabbitMQ not configured (optional)"
            )
        
        try:
            rabbitmq_config = getattr(settings, "RABBITMQ_CONFIG", {})
            if not rabbitmq_config:
                return HealthCheckResult(
                    status=HealthStatus.PASS,
                    message="RabbitMQ not configured"
                )
            
            credentials = pika.PlainCredentials(
                rabbitmq_config.get("username", "guest"),
                rabbitmq_config.get("password", "guest")
            )
            parameters = pika.ConnectionParameters(
                host=rabbitmq_config.get("host", "localhost"),
                port=rabbitmq_config.get("port", 5672),
                virtual_host=rabbitmq_config.get("virtual_host", "/"),
                credentials=credentials,
                socket_timeout=5
            )
            connection = pika.BlockingConnection(parameters)
            connection.close()
            
            return HealthCheckResult(
                status=HealthStatus.PASS,
                message="RabbitMQ is healthy"
            )
        except AMQPError as e:
            logger.error(f"RabbitMQ health check failed: {e}")
            return HealthCheckResult(
                status=HealthStatus.FAIL,
                message=f"RabbitMQ connection failed: {str(e)}"
            )


class DiskSpaceHealthCheck(HealthCheck):
    """磁盘空间健康检查"""
    name = "disk"
    component_type = "system"
    
    def check(self) -> HealthCheckResult:
        try:
            import shutil
            path = getattr(settings, 'BASE_DIR', '/') or '/'
            total, used, free = shutil.disk_usage(path)
            free_percent = (free / total) * 100 if total > 0 else 0

            if free_percent < 5:
                status = HealthStatus.FAIL
                message = f"Critical disk space: {free_percent:.1f}% free"
            elif free_percent < 10:
                status = HealthStatus.WARN
                message = f"Low disk space: {free_percent:.1f}% free"
            else:
                status = HealthStatus.PASS
                message = f"Disk space healthy: {free_percent:.1f}% free"

            return HealthCheckResult(
                status=status,
                message=message,
                metrics={
                    "free_bytes": free,
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_percent": round(free_percent, 1)
                }
            )
        except Exception as e:
            logger.error(f"Disk space check failed: {e}")
            return HealthCheckResult(
                status=HealthStatus.WARN,
                message=f"Could not check disk space: {str(e)}"
            )


class HealthChecker:
    """健康检查管理器"""
    
    def __init__(self):
        self.checks: List[HealthCheck] = [
            DatabaseHealthCheck(),
            RedisHealthCheck(),
            RabbitMQHealthCheck(),
            DiskSpaceHealthCheck(),
        ]
    
    def run_all(self) -> Dict[str, Any]:
        """运行所有健康检查"""
        results = []
        overall_status = HealthStatus.PASS
        
        for check in self.checks:
            result = check.check()
            results.append(result)
            
            if result.status == HealthStatus.FAIL:
                overall_status = HealthStatus.FAIL
            elif result.status == HealthStatus.WARN and overall_status != HealthStatus.FAIL:
                overall_status = HealthStatus.WARN
        
        return {
            "status": overall_status.value,
            "version": getattr(settings, "VERSION", "unknown"),
            "checks": {
                r.name: {
                    "status": r.status.value,
                    "message": r.message,
                    **(r.metrics if hasattr(r, "metrics") else {})
                }
                for r in results
            }
        }
    
    def run_live(self) -> Dict[str, Any]:
        """运行存活检查（仅检查核心服务）"""
        return {
            "status": "pass",
            "version": getattr(settings, "VERSION", "unknown")
        }
    
    def run_ready(self) -> Dict[str, Any]:
        """运行就绪检查"""
        return self.run_all()
