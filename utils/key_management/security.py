import secrets
from typing import Optional

from loguru import logger


def generate_secret_key(length: int = 50) -> str:
    """
    生成 Django SECRET_KEY
    
    使用 Python secrets 模块生成密码学安全的随机密钥
    
    Args:
        length: 密钥长度（默认为50个字符，Django建议至少50个字符）
    
    Returns:
        生成的 SECRET_KEY 字符串
    """
    if length < 32:
        raise ValueError("SECRET_KEY 长度至少需要32个字符")
    
    return secrets.token_urlsafe(length)


def generate_django_secret_key() -> str:
    """
    生成符合 Django 标准的 SECRET_KEY
    
    使用 Django 推荐的方式生成密钥
    
    Returns:
        Django 标准格式的 SECRET_KEY
    """
    try:
        from django.core.management.utils import get_random_secret_key
        return get_random_secret_key()
    except ImportError:
        return generate_secret_key(50)


def rotate_secret_key(current_key: Optional[str] = None) -> str:
    """
    轮换 SECRET_KEY
    
    Args:
        current_key: 当前的密钥（可选，用于记录）
    
    Returns:
        新的 SECRET_KEY
    """
    new_key = generate_secret_key(50)
    
    if current_key:
        logger.info("注意：轮换密钥后，所有已登录的用户会话将失效！")
    
    return new_key


if __name__ == "__main__":
    logger.info("生成 Django SECRET_KEY:")
    logger.info(f"方法1 (secrets): {generate_secret_key()}")
    logger.info(f"方法2 (Django):  {generate_django_secret_key()}")
