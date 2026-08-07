"""
密钥管理模块
提供 Django SECRET_KEY 的生成、轮换和多密钥签名功能
"""

# 从 security.py 导出
from framework.key_management.security import (
    generate_secret_key,
    generate_django_secret_key,
    rotate_secret_key,
)

# 从 key_rotation.py 导出
from framework.key_management.key_rotation import (
    KeyRotationManager,
    RotationKey,
    get_key_manager,
    get_rotatable_secret_key,
    get_all_secret_keys,
)

# 从 crypto.py 导出
from framework.key_management.crypto import (
    MultiKeySigner,
    MultiKeyTimestampSigner,
    multi_key_sign,
    multi_key_unsign,
    get_signer,
    get_timestamp_signer,
)

# 从 tasks.py 导出（Celery 任务）
try:
    from framework.key_management.tasks import (
        auto_rotate_secret_key,
        scan_tls_certificates,
        scan_secret_leaks,
        security_audit,
    )
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False
    auto_rotate_secret_key = None
    scan_tls_certificates = None
    scan_secret_leaks = None
    security_audit = None

__all__ = [
    # security.py
    'generate_secret_key',
    'generate_django_secret_key',
    'rotate_secret_key',
    
    # key_rotation.py
    'KeyRotationManager',
    'RotationKey',
    'get_key_manager',
    'get_rotatable_secret_key',
    'get_all_secret_keys',
    
    # crypto.py
    'MultiKeySigner',
    'MultiKeyTimestampSigner',
    'multi_key_sign',
    'multi_key_unsign',
    'get_signer',
    'get_timestamp_signer',
]

# Celery 相关（如果可用）
if HAS_CELERY:
    __all__ += [
        'auto_rotate_secret_key',
        'scan_tls_certificates',
        'scan_secret_leaks',
        'security_audit',
    ]
