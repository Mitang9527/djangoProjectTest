"""
统一的环境变量加载工具
确保整个项目使用一致的方式加载 .env 文件
"""
import os
from pathlib import Path
from loguru import logger

# 标记是否已加载
_env_loaded = False


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).resolve().parent.parent.parent


def load_env_file(env_file: str = ".env") -> bool:
    """
    加载环境变量文件（只加载一次）
    
    Args:
        env_file: 环境文件名，默认 .env
        
    Returns:
        bool: 是否成功加载
    """
    global _env_loaded
    
    if _env_loaded:
        return True
    
    project_root = get_project_root()
    env_path = project_root / env_file
    
    if not env_path.exists():
        logger.warning(f"环境文件不存在: {env_path}")
        return False
    
    # 优先使用 python-dotenv
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
        logger.info(f"已加载环境文件: {env_path}")
        _env_loaded = True
        return True
    except ImportError:
        logger.warning("python-dotenv 未安装，使用手动加载")
    
    # 降级方案：手动解析
    logger.info("使用手动方式加载环境变量")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    os.environ.setdefault(key, value)
        
        logger.info(f"已手动加载环境文件: {env_path}")
        _env_loaded = True
        return True
    except Exception as e:
        logger.error(f"加载环境文件失败: {e}")
        return False


def get_env_type() -> str:
    """获取当前环境类型"""
    return os.environ.get("ENV", "DEV").upper()


def is_production() -> bool:
    """是否为生产环境"""
    return get_env_type() == "PROD"

def is_development() -> bool:
    """是否为开发环境"""
    return get_env_type() == "DEV"
