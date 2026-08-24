"""
framework.config — 配置强类型校验。

上提 dev settings 中已局部使用的 pydantic 逻辑，统一为启动前可复用的 env 校验。
"""
from framework.config.validator import EnvSpec, check_required_env, validate_env

__all__ = ["EnvSpec", "validate_env", "check_required_env"]
