"""
读写分离路由单元测试
====================
验证 PrimaryReplicaRouter 的选库逻辑、事务感知，以及 install_replica /
parse_database_url 的条件注入能力。全程不真实连接数据库（router 只返回库别名）。
"""
import os
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.db import connections

from framework.db.replica import (
    REPLICA_ALIAS,
    PrimaryReplicaRouter,
    install_replica,
    parse_database_url,
)


class TestParseDatabaseUrl:
    def test_postgresql(self):
        d = parse_database_url("postgresql://u:p@db-host:5432/mydb")
        assert d["ENGINE"] == "django.db.backends.postgresql"
        assert d["HOST"] == "db-host"
        assert d["PORT"] == "5432"
        assert d["NAME"] == "mydb"
        assert d["USER"] == "u"
        assert d["PASSWORD"] == "p"

    def test_postgres_alias(self):
        d = parse_database_url("postgres://u@h/db")
        assert d["ENGINE"] == "django.db.backends.postgresql"
        assert d["HOST"] == "h"
        assert d["NAME"] == "db"

    def test_mysql(self):
        d = parse_database_url("mysql://u:p@h:3306/db")
        assert d["ENGINE"] == "django.db.backends.mysql"
        assert d["PORT"] == "3306"

    def test_sqlite_absolute(self):
        d = parse_database_url("sqlite:////tmp/replica.sqlite3")
        assert d["ENGINE"] == "django.db.backends.sqlite3"
        assert d["NAME"] == "/tmp/replica.sqlite3"

    def test_sqlite_memory(self):
        d = parse_database_url("sqlite://")
        assert d["ENGINE"] == "django.db.backends.sqlite3"
        assert d["NAME"] == ":memory:"

    def test_invalid_scheme(self):
        with pytest.raises(ValueError):
            parse_database_url("oracle://x/y")


class TestPrimaryReplicaRouter:
    def setup_method(self):
        self.router = PrimaryReplicaRouter()
        # 确保全局 DATABASES 在测试间干净
        self._saved = settings.DATABASES.copy()

    def teardown_method(self):
        # 还原，避免影响其它测试
        settings.DATABASES.clear()
        settings.DATABASES.update(self._saved)

    def test_no_replica_falls_back_to_default(self):
        # 当前测试环境未配置副本
        assert REPLICA_ALIAS not in settings.DATABASES
        assert self.router.db_for_read(User) == "default"
        assert self.router.db_for_write(User) == "default"

    def test_allow_migrate_only_default(self):
        assert self.router.allow_migrate("default", "myapp") is True
        assert self.router.allow_migrate(REPLICA_ALIAS, "myapp") is False

    def test_with_replica_reads_replica(self):
        settings.DATABASES[REPLICA_ALIAS] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
        assert self.router.db_for_read(User) == REPLICA_ALIAS
        assert self.router.db_for_write(User) == "default"
        assert self.router.allow_migrate(REPLICA_ALIAS, "myapp") is False
        assert self.router.allow_migrate("default", "myapp") is True

    def test_in_atomic_block_reads_default(self):
        settings.DATABASES[REPLICA_ALIAS] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
        # 事务感知：在 default 写事务内，读必须回退 default，避免跨库事务
        with mock.patch.object(connections["default"], "in_atomic_block", True):
            assert self.router.db_for_read(User) == "default"

    def test_allow_relation_between_primary_and_replica(self):
        class _Obj:
            def __init__(self, db):
                self._state = type("S", (), {"db": db})()

        o1 = _Obj("default")
        o2 = _Obj(REPLICA_ALIAS)
        assert self.router.allow_relation(o1, o2) is True

        o3 = _Obj("other_db")
        assert self.router.allow_relation(o1, o3) is None


class TestInstallReplica:
    def test_no_env_returns_unchanged(self):
        databases = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
        routers: list = []
        out_db, out_rt = install_replica(databases, routers)
        assert REPLICA_ALIAS not in out_db
        assert out_rt == []
        # 不修改原列表
        assert routers == []

    def test_with_env_injects_replica_and_router(self, monkeypatch):
        monkeypatch.setenv("DB_REPLICA_URL", "postgresql://u:p@replica-host:5432/mydb")
        default = {
            "ENGINE": "django_prometheus.db.backends.postgresql",
            "NAME": "mydb",
            "_pool": {"enabled": True, "min_size": 2},
        }
        databases = {"default": default}
        routers: list = []
        out_db, out_rt = install_replica(databases, routers)

        assert REPLICA_ALIAS in out_db
        replica = out_db[REPLICA_ALIAS]
        # 复用主库同构的 ENGINE 与连接池
        assert replica["ENGINE"] == "django_prometheus.db.backends.postgresql"
        assert replica["_pool"] == {"enabled": True, "min_size": 2}
        # 用副本连接字段覆盖
        assert replica["HOST"] == "replica-host"
        assert replica["NAME"] == "mydb"
        # router 已注册
        assert any(isinstance(r, PrimaryReplicaRouter) for r in out_rt)

    def test_invalid_env_is_ignored(self, monkeypatch):
        monkeypatch.setenv("DB_REPLICA_URL", "oracle://x/y")
        databases = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
        out_db, out_rt = install_replica(databases, [])
        assert REPLICA_ALIAS not in out_db
        assert out_rt == []

    def test_replica_already_defined_not_duplicated(self, monkeypatch):
        monkeypatch.setenv("DB_REPLICA_URL", "postgresql://u:p@h:5432/db")
        databases = {
            "default": {"ENGINE": "django.db.backends.postgresql", "NAME": "db"},
            REPLICA_ALIAS: {"ENGINE": "django.db.backends.postgresql", "NAME": "db_rep"},
        }
        out_db, out_rt = install_replica(databases, [])
        # 不覆盖已存在副本；router 仍追加一次
        assert out_db[REPLICA_ALIAS]["NAME"] == "db_rep"
        assert len([r for r in out_rt if isinstance(r, PrimaryReplicaRouter)]) == 1
