"""
环境变量强类型校验（基于 pydantic）。

可在 Django setup 之前运行，作为启动自检：校验关键环境变量是否齐备、
类型/取值是否合法，避免错误配置在运行很久后才暴露。

用法::

    from framework.config import validate_env
    ok, errors = validate_env("DATABASE_URL")
    if not ok:
        raise RuntimeError("配置校验失败: " + "; ".join(errors))
"""
import os
from typing import List, Tuple

from pydantic import BaseModel, ValidationError, field_validator


class EnvSpec(BaseModel):
    SECRET_KEY: str
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    SENTRY_DSN: str = ""

    @field_validator("LOG_LEVEL")
    @classmethod
    def _lvl(cls, v: str) -> str:
        if str(v).upper() not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("LOG_LEVEL 必须是 DEBUG/INFO/WARNING/ERROR")
        return str(v).upper()


def _coerce_bool(val: str) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def validate_env(*extra_required: str) -> Tuple[bool, List[str]]:
    """校验关键环境变量，返回 (是否通过, 错误列表)。"""
    raw = {
        "SECRET_KEY": os.environ.get("SECRET_KEY", ""),
        "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO"),
        "DEBUG": _coerce_bool(os.environ.get("DEBUG", "False")),
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        "REDIS_URL": os.environ.get("REDIS_URL", ""),
        "SENTRY_DSN": os.environ.get("SENTRY_DSN", ""),
    }
    missing = [n for n in extra_required if not os.environ.get(n)]
    try:
        EnvSpec(**raw)
    except ValidationError as e:
        errs = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        return (False, errs + missing)
    if missing:
        return (False, missing)
    return (True, [])


def check_required_env(*names: str) -> List[str]:
    """返回缺失的必需环境变量名列表（空表示齐备）。"""
    return [n for n in names if not os.environ.get(n)]
