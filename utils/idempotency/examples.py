"""
幂等键使用示例
==============

1. 装饰器：订单创建
2. 装饰器：带 fallback 的幂等支付
3. 上下文管理器：复杂场景
4. DRF ViewSet 集成
"""
from __future__ import annotations

# ============================================================
# 示例 1：装饰器 - 订单创建
# ============================================================
def example_1_decorator():
    """最常见的场景：防重创建订单"""
    from utils.idempotency import idempotent
    from utils.idempotency.core import set_default_backend, LocalMemoryIdempotencyBackend

    # 演示用：切到本地内存后端（无 Redis 时）
    set_default_backend(LocalMemoryIdempotencyBackend())

    call_count = 0

    @idempotent(key_fields=["order_id"], ttl=600)
    def create_order(order_id: str, amount: int, user_id: str):
        nonlocal call_count
        call_count += 1
        # 模拟业务：调用支付、扣库存、写订单表
        return {
            "order_id": order_id,
            "amount": amount,
            "user_id": user_id,
            "status": "created",
            "trade_no": f"T{order_id}",
        }

    # 第一次：执行
    r1 = create_order("O001", 100, "U1")
    # 第二次：重放
    r2 = create_order("O001", 100, "U1")
    assert r1 == r2, "响应必须一致"
    assert call_count == 1, f"业务应只执行 1 次，实际 {call_count}"

    # 不同 order_id：另一次业务
    create_order("O002", 200, "U1")
    assert call_count == 2

    print(f"[示例1] 装饰器幂等通过：业务仅执行 {call_count} 次")


# ============================================================
# 示例 2：指纹冲突检测
# ============================================================
def example_2_fingerprint_conflict():
    """同样的 key 但参数不一致 → 拒绝"""
    from utils.idempotency import idempotent
    from utils.idempotency.core import set_default_backend, LocalMemoryIdempotencyBackend
    from utils.idempotency.exceptions import IdempotencyConflict

    # 切换到本地内存后端，避免污染 Redis
    set_default_backend(LocalMemoryIdempotencyBackend())

    @idempotent(key_fields=["order_id"], ttl=600)
    def pay(order_id: str, amount: int):
        return {"order_id": order_id, "amount": amount, "status": "paid"}

    pay("P001", 100)
    try:
        pay("P001", 200)  # 同样的 key，amount 不同 → 冲突
    except IdempotencyConflict as e:
        print(f"[示例2] 检测到指纹冲突：{e}")


# ============================================================
# 示例 3：上下文管理器
# ============================================================
def example_3_context_manager():
    """更灵活：分步骤存储响应"""
    from utils.idempotency import idempotent_context
    from utils.idempotency.core import set_default_backend, LocalMemoryIdempotencyBackend

    set_default_backend(LocalMemoryIdempotencyBackend())

    def process_upload(upload_id: str, file_path: str):
        with idempotent_context(
            key=f"upload:{upload_id}",
            fingerprint=f"{upload_id}:{file_path}",
            ttl=300,
        ) as ctx:
            if ctx.is_replay:
                print(f"  → 命中重放，响应: {ctx.replayed_response}")
                return ctx.replayed_response

            # 业务：上传、转码、生成预览
            response = {
                "upload_id": upload_id,
                "file_path": file_path,
                "preview_url": f"https://cdn.example.com/{upload_id}.jpg",
                "duration": 120,
            }
            ctx.store(response)
            return response

    print("[示例3] 第一次调用:")
    r1 = process_upload("UP001", "/tmp/a.mp4")
    print(f"  → 响应: {r1}")

    print("[示例3] 第二次调用（重放）:")
    r2 = process_upload("UP001", "/tmp/a.mp4")
    assert r1 == r2


# ============================================================
# 示例 4：DRF 集成（伪代码，需要在 ViewSet 中测试）
# ============================================================
def example_4_drf_viewset():
    """DRF ViewSet 通过 header 接收 Idempotency-Key"""
    # 见 utils.idempotency.drf.IdempotencyKeyMixin（需 Django + DRF 环境）
    # from rest_framework import viewsets
    #
    # class OrderViewSet(IdempotencyKeyMixin, viewsets.ModelViewSet):
    #     queryset = Order.objects.all()
    #     serializer_class = OrderSerializer
    #     idempotency_ttl = 600
    #
    # 客户端请求：
    # POST /api/orders/
    # Headers: Idempotency-Key: <uuid>
    # Body: {"items": [...], "total": 100}
    print("[示例4] 见 utils/idempotency/drf.py 完整源码 + 项目 ViewSet 集成示例")


if __name__ == "__main__":
    example_1_decorator()
    example_2_fingerprint_conflict()
    example_3_context_manager()
    example_4_drf_viewset()
    print("\n所有示例执行完毕")
