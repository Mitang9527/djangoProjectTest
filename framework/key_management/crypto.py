"""密钥加密/签名器。

基于 Django Signing 实现支持多密钥版本化的签名器：签名时用当前密钥，验签时按
版本回溯历史密钥，支撑密钥平滑轮换（旧密钥签发的密文仍可解密）。
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from django.core.signing import Signer, TimestampSigner
from django.utils.crypto import constant_time_compare
from typing import Any, Optional
from framework.key_management.key_rotation import get_all_secret_keys, get_rotatable_secret_key


class MultiKeySigner(Signer):
    """
    支持多密钥的签名器
    
    签名时使用主密钥，验证时尝试所有有效密钥
    """
    
    def __init__(self, key=None, sep=':', salt=None):
        # 签名时使用主密钥
        if key is None:
            key = get_rotatable_secret_key()
        super().__init__(key, sep, salt)
    
    def sign(self, value: str) -> str:
        """使用主密钥签名"""
        return super().sign(value)
    
    def unsign(self, signed_value: str) -> str:
        """尝试所有有效密钥来验证签名"""
        keys = get_all_secret_keys()
        
        last_exception = None
        for key in keys:
            try:
                # 使用当前密钥创建临时签名器
                signer = Signer(key, self.sep, self.salt)
                return signer.unsign(signed_value)
            except Exception as e:
                last_exception = e
                continue
        
        # 如果所有密钥都失败，抛出最后一个异常
        raise last_exception or ValueError("No valid keys to verify signature")


class MultiKeyTimestampSigner(TimestampSigner):
    """
    支持多密钥的时间戳签名器
    """
    
    def __init__(self, key=None, sep=':', salt=None):
        if key is None:
            key = get_rotatable_secret_key()
        super().__init__(key, sep, salt)
    
    def sign(self, value: str) -> str:
        """使用主密钥签名"""
        return super().sign(value)
    
    def unsign(self, signed_value: str, max_age: Optional[int] = None) -> str:
        """尝试所有有效密钥来验证签名"""
        keys = get_all_secret_keys()
        
        last_exception = None
        for key in keys:
            try:
                signer = TimestampSigner(key, self.sep, self.salt)
                return signer.unsign(signed_value, max_age)
            except Exception as e:
                last_exception = e
                continue
        
        raise last_exception or ValueError("No valid keys to verify signature")


def multi_key_sign(value: Any, salt: Optional[str] = None) -> str:
    """
    使用主密钥签名数据
    
    Args:
        value: 要签名的数据
        salt: 可选的盐值
    
    Returns:
        签名字符串
    """
    signer = MultiKeySigner(salt=salt)
    return signer.sign(str(value))


def multi_key_unsign(signed_value: str, salt: Optional[str] = None) -> str:
    """
    使用所有有效密钥验证签名
    
    Args:
        signed_value: 签名后的值
        salt: 可选的盐值
    
    Returns:
        原始值
    
    Raises:
        签名验证失败时抛出异常
    """
    signer = MultiKeySigner(salt=salt)
    return signer.unsign(signed_value)


def get_signer(salt: Optional[str] = None) -> MultiKeySigner:
    """获取多密钥签名器实例"""
    return MultiKeySigner(salt=salt)


def get_timestamp_signer(salt: Optional[str] = None) -> MultiKeyTimestampSigner:
    """获取多密钥时间戳签名器实例"""
    return MultiKeyTimestampSigner(salt=salt)
