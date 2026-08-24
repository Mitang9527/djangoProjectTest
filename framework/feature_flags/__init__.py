"""
framework.feature_flags — 功能开关（灰度 / 按需开启）。
"""
from framework.feature_flags.flags import feature_flag, get_flag

__all__ = ["get_flag", "feature_flag"]
