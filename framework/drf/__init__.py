"""
framework.drf
=========

DRF 业务开发套件（聚合 3 个高频工具模块）：

- :mod:`framework.drf.serializers`  序列化器扩展（Bulk / Recursive / Encrypted / Desensitized / BaseModel）
- :mod:`framework.drf.validators`   业务校验器（手机 / 身份证 / 密码强度 / 规则引擎等）
- :mod:`framework.drf.queryset`     ORM 增强（软删除 / 乐观锁 / 批量 upsert / BaseModel）

零新增依赖：仅依赖项目已有的 DRF + django.db。

便捷导入
--------

>>> from framework.drf import (
...     # serializers
...     BulkSerializerMixin, RecursiveField, EncryptedField,
...     DesensitizedCharField, BaseModelSerializer,
...     # validators
...     is_valid_chinese_mobile, is_valid_id_card_cn, password_strength,
...     validate_chinese_mobile, RuleEngine,
...     # queryset
...     SoftDeleteModel, OptimisticLockMixin, BaseModel, bulk_create_or_update,
... )
"""
# sync-init: skip

from .serializers import (
    BulkSerializerMixin,
    RecursiveField,
    EncryptedField,
    DesensitizedCharField,
    BaseModelSerializer,
)

from .validators import (
    # --- is_valid_* ---
    is_valid_chinese_mobile,
    is_valid_id_card_cn,
    is_valid_email,
    is_valid_url,
    is_valid_ipv4,
    is_valid_ipv6,
    is_valid_ip,
    is_valid_bank_card,
    is_valid_chinese_name,
    password_strength,
    PasswordStrengthResult,
    # --- validate_* (DRF 风格抛错) ---
    validate_chinese_mobile,
    validate_id_card_cn,
    validate_email,
    validate_url,
    validate_ip,
    validate_bank_card,
    validate_password,
    # --- 规则引擎 ---
    RuleEngine,
    RuleResult,
)

from .queryset import (
    SoftDeleteModel,
    SoftDeleteQuerySet,
    SoftDeleteManager,
    AllObjectsManager,
    OptimisticLockMixin,
    TimestampMixin,
    BaseModel,
    bulk_create_or_update,
    ConcurrentModificationError,
    TenantScopedQuerySet,
    TenantScopedManager,
    get_request_tenant,
)

__all__ = [
    # serializers
    "BulkSerializerMixin",
    "RecursiveField",
    "EncryptedField",
    "DesensitizedCharField",
    "BaseModelSerializer",
    # validators — is_valid_*
    "is_valid_chinese_mobile",
    "is_valid_id_card_cn",
    "is_valid_email",
    "is_valid_url",
    "is_valid_ipv4",
    "is_valid_ipv6",
    "is_valid_ip",
    "is_valid_bank_card",
    "is_valid_chinese_name",
    "password_strength",
    "PasswordStrengthResult",
    # validators — validate_*
    "validate_chinese_mobile",
    "validate_id_card_cn",
    "validate_email",
    "validate_url",
    "validate_ip",
    "validate_bank_card",
    "validate_password",
    # validators — 规则引擎
    "RuleEngine",
    "RuleResult",
    # queryset
    "SoftDeleteModel",
    "SoftDeleteQuerySet",
    "SoftDeleteManager",
    "AllObjectsManager",
    "OptimisticLockMixin",
    "TimestampMixin",
    "BaseModel",
    "bulk_create_or_update",
    "ConcurrentModificationError",
    "TenantScopedQuerySet",
    "TenantScopedManager",
    "get_request_tenant",
]
