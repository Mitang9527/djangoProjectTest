"""
敏感值字段加密工具测试（framework.security.sensitive）。

覆盖：
- 工具层：encrypt/decrypt 往返、空值透传、版本前缀、多密钥轮换后旧密文可解、
  坏密文 / 未知版本抛 InvalidToken、mask_value 脱敏；
- 字段层：SensitiveField 落库为 v1: 密文、读库还原明文、幂等（不二次加密）。
"""

import pytest
from cryptography.fernet import InvalidToken
from django.db import connection, models

from framework.security import sensitive

# 测试环境 SECRET_KEY（conftest 固定），多密钥用例避开该值
_TEST_SECRET_KEY = "test-secret-key-not-for-production-use-only-at-least-10-chars"  # noqa: S105


class _SecretModel(models.Model):
    """动态模型：验证 SensitiveField 的真实落库/读库行为。"""

    secret = sensitive.SensitiveField(blank=True, default="")
    label = models.CharField(max_length=64, default="")

    class Meta:
        app_label = "framework"


@pytest.fixture
def secret_table(db):
    """动态建表并在测试后删除（SQLite 事务内禁止 schema_editor，用原生 SQL）。"""
    table = _SecretModel._meta.db_table
    with connection.cursor() as cur:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {table} "
            "(id integer PRIMARY KEY AUTOINCREMENT NOT NULL, "
            "secret text NOT NULL, label varchar(64) NOT NULL)"
        )
    yield
    with connection.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table}")


# ── 工具层 ─────────────────────────────────────────────


def test_roundtrip():
    value = "sk-3f9a-c1d4-88b2"
    protected = sensitive.encrypt_value(value)
    assert sensitive.decrypt_value(protected) == value


def test_version_prefix():
    protected = sensitive.encrypt_value("token-abc")
    assert protected.startswith("v1:")


def test_empty_passthrough():
    assert sensitive.encrypt_value("") == ""
    assert sensitive.encrypt_value(None) is None
    assert sensitive.decrypt_value("") == ""
    assert sensitive.decrypt_value(None) is None


def test_multi_key_rotation_after_rotate(monkeypatch):
    """轮换后旧密文仍可解：加密用旧主密钥，解密时新主密钥失败但旧密钥兜住。"""
    old_key, new_key = "old-primary-key-111", "new-primary-key-222"
    monkeypatch.setattr(sensitive, "get_rotatable_secret_key", lambda: old_key)
    monkeypatch.setattr(sensitive, "get_all_secret_keys", lambda: [old_key])
    protected = sensitive.encrypt_value("legacy-secret")

    # 轮换：主密钥换成 new_key，活跃列表 [new_key, old_key]
    monkeypatch.setattr(sensitive, "get_rotatable_secret_key", lambda: new_key)
    monkeypatch.setattr(sensitive, "get_all_secret_keys", lambda: [new_key, old_key])
    assert sensitive.decrypt_value(protected) == "legacy-secret"

    # 新数据用新主密钥加密，往返正常
    protected2 = sensitive.encrypt_value("fresh-secret")
    assert sensitive.decrypt_value(protected2) == "fresh-secret"


def test_invalid_ciphertext_raises(monkeypatch):
    monkeypatch.setattr(sensitive, "get_all_secret_keys", lambda: [])
    with pytest.raises(InvalidToken):
        sensitive.decrypt_value("v1:not-valid-ciphertext")
    with pytest.raises(InvalidToken):
        sensitive.decrypt_value("v9:AAAA")


def test_mask_value():
    # 15 字符：保留前后各 2，中间 11 个星
    assert sensitive.mask_value("sk-abcdef123456") == "sk***********56"
    assert sensitive.mask_value("") == ""


# ── 字段层 ─────────────────────────────────────────────


def test_model_stores_ciphertext_returns_plaintext(secret_table):
    obj = _SecretModel.objects.create(secret="my-api-secret", label="provider-a")
    # 落库必须是密文（直接查数据库原始值）
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT secret FROM {_SecretModel._meta.db_table} WHERE id = %s",  # noqa: S608 - 表名为框架内部常量，非用户输入
            [obj.id],
        )
        raw = cur.fetchone()[0]
    assert raw.startswith("v1:")
    assert "my-api-secret" not in raw

    # 读库自动还原明文
    obj.refresh_from_db()
    assert obj.secret == "my-api-secret"  # noqa: S105


def test_model_empty_and_idempotent(secret_table):
    obj = _SecretModel.objects.create(secret="", label="empty")
    obj.refresh_from_db()
    assert obj.secret == ""

    # 已是密文的值再走 get_prep_value 不二次加密
    protected = sensitive.encrypt_value("token-xyz")
    assert _SecretModel._meta.get_field("secret").get_prep_value(protected) == protected
