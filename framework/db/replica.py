"""
数据库读写分离（主从复制）路由：通过 Django ``DATABASE_ROUTERS`` 把读流量引向
只读副本（replica），写流量留在主库（default）。

零侵入、缺省安全：未配置副本环境变量时读写同库，行为与改造前一致；仅当设置
``DB_REPLICA_URL``（或 ``DB_REPLICA_DSN``）时才启用副本，连接串缺失/解析失败
自动降级单库不报错。事务感知：``default`` 写事务（atomic 块）内读强制回退
``default``，避免「先读 replica 后写 default」跨库崩溃。replica 由主库流复制
同步，只读、绝不跑 migration（``allow_migrate`` 限定仅 ``default``）。

接入方式（各环境 settings）::

    from framework.db.replica import install_replica
    DATABASES, DATABASE_ROUTERS = install_replica(DATABASES, DATABASE_ROUTERS)

配置只读副本（生产示例）::

    export DB_REPLICA_URL="postgresql://replica_user:secret@pg-replica:5432/mydb"

DSN 支持 scheme：``postgresql``/``postgres``/``mysql``/``mysql+mysqlconnector``/
``mysql+pymysql``/``sqlite``/``sqlite3``。

⚠️ 铁律：写操作/事务务必显式绑定 ``default``（``Model.objects.using('default')``
或 ``@transaction.atomic(using='default')``）；不要依赖 router 把长事务内读也路由
到 replica；replica 是只读副本，任何写库操作（含 migrate、数据修正脚本）都必须
指向 ``default``。
"""
from __future__ import annotations

import logging
import os
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

REPLICA_ALIAS = "replica"


# DSN 解析
_ENGINE_MAP = {
    "postgresql": "django.db.backends.postgresql",
    "postgres": "django.db.backends.postgresql",
    "mysql": "django.db.backends.mysql",
    "mysql+mysqlconnector": "django.db.backends.mysql",
    "mysql+pymysql": "django.db.backends.mysql",
    "sqlite": "django.db.backends.sqlite3",
    "sqlite3": "django.db.backends.sqlite3",
}


def parse_database_url(url: str) -> dict:
    """把数据库连接串解析为 Django ``DATABASES[alias]`` 字典。

    支持常见 scheme（postgresql/mysql/sqlite 等），返回 ENGINE/NAME/HOST/PORT/
    USER/PASSWORD 最小配置（注入 replica 时再叠加 default 的 ENGINE 与 _pool）。
    """
    if not url or not isinstance(url, str):
        raise ValueError("DB_REPLICA_URL 为空或类型错误")

    split = urlsplit(url)
    scheme = (split.scheme or "").lower()
    if scheme not in _ENGINE_MAP:
        raise ValueError(f"不支持的数据库 scheme：{scheme!r}（支持 {sorted(_ENGINE_MAP)}）")

    engine = _ENGINE_MAP[scheme]
    conf: dict = {"ENGINE": engine}

    if scheme in ("sqlite", "sqlite3"):
        # sqlite:///abs/path -> /abs/path，sqlite:// -> :memory:；兼容四斜杠写法
        path = split.path or ""
        if path.startswith("/"):
            conf["NAME"] = "/" + path.lstrip("/")
        elif split.netloc:
            # sqlite://host/path 形态，罕见但兜底
            conf["NAME"] = split.netloc + path.lstrip("/")
        else:
            conf["NAME"] = ":memory:"
        return conf

    conf["NAME"] = unquote(split.path.lstrip("/")) if split.path else ""
    conf["USER"] = unquote(split.username) if split.username else ""
    conf["PASSWORD"] = unquote(split.password) if split.password else ""
    conf["HOST"] = split.hostname or ""
    conf["PORT"] = str(split.port) if split.port else ""
    return conf


# 主从路由
class PrimaryReplicaRouter:
    """主库写、副本读。未配置副本时读写同库。"""

    def db_for_read(self, model, **hints):
        from django.conf import settings
        from django.db import connections

        # 事务感知：default 写事务内读必须同库，否则后续写落 replica 报只读错误
        try:
            if connections["default"].in_atomic_block:
                return "default"
        except Exception:  # pragma: no cover - 防御性兜底
            pass

        if "replica" in settings.DATABASES:
            return REPLICA_ALIAS
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # 主从是同一份数据的两个副本，允许跨库关系存在
        if obj1._state.db in {"default", REPLICA_ALIAS} and obj2._state.db in {
            "default",
            REPLICA_ALIAS,
        }:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # 仅主库执行迁移；replica 由主库流复制，不跑迁移
        return db == "default"


# 条件注入（供各环境 settings 调用）
def _get_replica_url() -> str | None:
    return os.environ.get("DB_REPLICA_URL") or os.environ.get("DB_REPLICA_DSN")


def install_replica(databases: dict, routers: list | None = None) -> tuple[dict, list]:
    """设置 ``DB_REPLICA_URL``/``DB_REPLICA_DSN`` 时向 DATABASES 注入 replica 库，
    并把 :class:`PrimaryReplicaRouter` 追加进 routers。

    副本库复用 default 的 ``ENGINE`` 与 ``_pool``（连接池），仅用 DSN 连接字段
    覆盖 host/port/name/user/password。

    :param databases: 当前 ``DATABASES`` 字典（原地增强并返回，支持
                      ``DATABASES, DATABASE_ROUTERS = install_replica(...)``）
    :param routers: 当前 ``DATABASE_ROUTERS`` 列表（默认空）
    :returns: (增强后的 databases, 增强后的 routers)
    """
    routers = list(routers or [])

    replica_url = _get_replica_url()
    if not replica_url:
        return databases, routers

    # 已存在 replica 配置则不重复注入（兼容手动定义副本的场景）
    if REPLICA_ALIAS in databases:
        if not any(isinstance(r, PrimaryReplicaRouter) for r in routers):
            routers.append(PrimaryReplicaRouter())
        return databases, routers

    try:
        parsed = parse_database_url(replica_url)
    except ValueError as exc:
        logger.warning("DB_REPLICA_URL 解析失败，读写分离未启用：%s", exc)
        return databases, routers

    default = databases.get("default", {})
    replica = dict(default)          # 浅拷贝主库配置
    replica.update(parsed)           # 用副本连接字段覆盖
    # 引擎同构：主库为 django_prometheus 包装的 postgresql/mysql 且副本同类型时
    # 复用主库包装引擎（保持指标采集一致），否则用 DSN 标准引擎（防 sqlite 错套）
    default_engine = default.get("ENGINE", "")
    if (
        "django_prometheus" in default_engine
        and default_engine.endswith(("postgresql", "mysql"))
        and replica["ENGINE"].endswith(("postgresql", "mysql"))
    ):
        replica["ENGINE"] = default_engine
    replica["_pool"] = dict(default.get("_pool", {}))  # 副本同样支持连接池
    # replica 是只读副本，迁移由主库复制，移除可能的写相关项
    replica.pop("CONN_MAX_AGE", None)
    databases[REPLICA_ALIAS] = replica

    if not any(isinstance(r, PrimaryReplicaRouter) for r in routers):
        routers.append(PrimaryReplicaRouter())

    logger.info("已启用数据库读写分离：副本库（%s）指向 %s", REPLICA_ALIAS, parsed.get("HOST") or parsed.get("NAME"))
    return databases, routers
