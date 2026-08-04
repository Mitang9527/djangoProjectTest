"""
幂等键工具包
=============

解决「重复请求 = 重复副作用」问题：支付、订单、消息发送、状态变更等场景
可通过本工具实现 exactly-once / at-most-once 语义。

快速开始
--------

**装饰器用法（推荐）**::

    from framework.idempotency import idempotent

    @idempotent(key_fields=["order_id"], ttl=600)
    def create_order(order_id, amount, user_id):
        # 业务逻辑：可能产生外部副作用
        ...

    # 第一次调用：正常执行
    create_order(order_id="O001", amount=100, user_id="U1")
    # 第二次调用（相同 order_id）：直接返回缓存的响应，不重复执行
    create_order(order_id="O001", amount=100, user_id="U1")


**显式上下文管理器**::

    from framework.idempotency import idempotent_context

    def create_order_view(request):
        with idempotent_context(key=request.headers.get("Idempotency-Key")) as ctx:
            if ctx.is_replay:
                return ctx.replayed_response  # 命中，返回上次响应

            # 业务处理
            response = do_create_order(request)
            ctx.store(response)  # 持久化本次响应
            return response


**DRF 集成**::

    from framework.idempotency.drf import IdempotencyKeyMixin

    class OrderViewSet(IdempotencyKeyMixin, viewsets.ModelViewSet):
        idempotency_ttl = 600
        idempotency_key_header = "HTTP_IDEMPOTENCY_KEY"
"""
from .core import (
    IdempotencyBackend,
    IdempotencyRecord,
    IdempotencyStatus,
    IdempotencyContext,
    idempotent_context,
    idempotent,
    get_default_backend,
    set_default_backend,
)

__all__ = [
    "IdempotencyBackend",
    "IdempotencyRecord",
    "IdempotencyStatus",
    "IdempotencyContext",
    "idempotent_context",
    "idempotent",
    "get_default_backend",
    "set_default_backend",
]
