"""
framework.testing — 测试工具集。

提供 JWTAPIClient（自动带 Bearer）与 ModelFactory（轻量工厂基类），
降低 tests/ 编写成本。
"""
from framework.testing.client import JWTAPIClient
from framework.testing.factories import ModelFactory

__all__ = ["JWTAPIClient", "ModelFactory"]
