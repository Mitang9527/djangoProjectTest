"""
Celery 定时任务：自动轮换 SECRET_KEY

使用此任务前需要配置 Celery beat
"""
import os
from loguru import logger

try:
    from celery import shared_task
except ImportError:
    logger.warning("Celery 未安装，任务不可用")
    # 创建一个装饰器兼容 mock
    def shared_task(func):
        return func


@shared_task(name='key_management.auto_rotate_secret_key')
def auto_rotate_secret_key(days=30):
    """
    自动轮换 SECRET_KEY 的 Celery 任务
    
    Args:
        days: 密钥轮换周期（默认30天）
    """
    logger.info(f"开始执行自动密钥轮换任务（周期：{days}天）")
    
    try:
        # 导入放在这里避免 Django 初始化问题
        from utils.key_management import get_key_manager
        
        manager = get_key_manager()
        
        # 检查是否需要轮换
        if not should_rotate(manager, days):
            logger.info("当前密钥还不需要轮换")
            return {"status": "skipped", "message": "不需要轮换"}
        
        # 执行轮换
        logger.info("开始轮换密钥...")
        new_key = manager.rotate_key(keep_old_days=days)
        
        logger.success(f"密钥自动轮换成功！")
        logger.info(f"新密钥前缀: {new_key[:15]}...")
        
        return {
            "status": "success",
            "new_key_prefix": new_key[:15],
            "old_key_kept_days": days
        }
        
    except Exception as e:
        logger.error(f"自动密钥轮换失败: {e}")
        return {"status": "error", "message": str(e)}


def should_rotate(manager, days):
    """判断是否应该轮换密钥"""
    from datetime import datetime
    
    keys_info = manager.get_key_info()
    
    # 找到主密钥
    primary_key = None
    for key in keys_info:
        if key['is_primary']:
            primary_key = key
            break
    
    if not primary_key:
        logger.warning("没有找到主密钥，执行轮换")
        return True
    
    try:
        created_at = datetime.fromisoformat(primary_key['created_at'])
        days_old = (datetime.now() - created_at).days
        
        logger.info(f"当前主密钥已使用 {days_old} 天")
        
        if days_old >= days:
            logger.info(f"达到轮换阈值（{days}天）")
            return True
        else:
            logger.info(f"还未到轮换时间（还剩 {days - days_old} 天）")
            return False
            
    except Exception as e:
        logger.error(f"检查密钥时间失败: {e}")
        return False
