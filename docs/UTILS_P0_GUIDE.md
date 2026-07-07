# utils P0 模块使用指南

`utils/` 目录下新增三个 P0 工具集，覆盖「分布式 + 容错」核心诉求。

| 模块 | 文件数 | 单测 | 用途 |
|------|--------|------|------|
| `utils/idempotency/` | 5 | 7 ✅ | 幂等键（防重 + body 篡改检测） |
| `utils/locks/` | 3 | 8 ✅ | 分布式锁（互斥/可重入/看门狗） |
| `utils/reliability/` | 6 | 11 ✅ | 重试/熔断/隔离/降级 四件套 |

合计 **26 个单测全部通过**，examples 可直接 `python utils/<module>/examples.py` 跑通。

---

## 1. utils/idempotency — 幂等键

### 解决的问题
- 支付/订单/消息发送场景下，「重复点击 = 重复扣款」
- 客户端网络重试导致的「同一请求多次落地」
- 业务侧需要「已处理过这个 key，请返回上次结果」语义

### 核心 API

```python
from utils.idempotency import idempotent, idempotent_context

# ===== 装饰器 =====
@idempotent(key_fields=["order_id"], ttl=600)
def create_order(order_id, amount, user_id):
    return call_payment_service(order_id, amount)  # 仅首次执行

# ===== 上下文管理器（更灵活）=====
with idempotent_context(key="upload:UP001", fingerprint=fp, ttl=300) as ctx:
    if ctx.is_replay:
        return ctx.replayed_response   # 命中重放
    response = do_upload()
    ctx.store(response)               # 持久化响应
    return response
```

### 关键设计

| 概念 | 说明 |
|------|------|
| **key** | 业务唯一标识，决定是否同一请求 |
| **fingerprint** | 请求体 hash，检测 body 篡改（同样的 key 但参数不同 → 抛 IdempotencyConflict） |
| **状态机** | `IN_PROGRESS → COMPLETED / FAILED` |
| **ignore_fields** | fingerprint 排除字段（如 trace_id 之类的非业务字段） |

### 后端
- **Redis**（生产推荐）：原子 SETNX + EX，跨 worker 共享
- **LocalMemory**（测试/单机）：进程内 dict
- 切换：`set_default_backend(LocalMemoryIdempotencyBackend())`

### DRF 集成

```python
from utils.idempotency.drf import IdempotencyKeyMixin

class OrderViewSet(IdempotencyKeyMixin, viewsets.ModelViewSet):
    idempotency_ttl = 600
    idempotency_key_header = "HTTP_IDEMPOTENCY_KEY"  # 默认

# 客户端：
# POST /api/orders/
# Headers: Idempotency-Key: <uuid>
# Body: {"items": [...], "total": 100}
```

---

## 2. utils/locks — 分布式锁

### 解决的问题
- 库存/订单并发：避免超卖
- Celery 任务防重：避免同一任务被多 worker 抢到
- 关键区段互斥：保证「读-改-写」原子

### 核心 API

```python
from utils.locks import RedisLock, locked, RedLock

# ===== 上下文管理器（推荐）=====
with RedisLock("order:123:pay", ttl=30, wait=5):
    do_payment()

# ===== 装饰器 =====
@locked(key=lambda order_id: f"order:{order_id}:pay", ttl=10, wait=2)
def pay(order_id, amount):
    ...

# ===== 长任务 + 看门狗 =====
with RedisLock("long_task", ttl=3, auto_renewal=True):
    run_long_task()  # 每 ttl/3 自动续期
```

### 关键特性

| 特性 | 说明 |
|------|------|
| **可重入** | 同一线程可多次获取（`reentrant=True`） |
| **看门狗** | `auto_renewal=True` 时启动后台线程，每 ttl/3 续期 |
| **Lua 释放** | 防误删：仅 owner 匹配的 token 才能 DEL |
| **非阻塞/阻塞** | `wait=0` 非阻塞（抛 LockAcquireError），`wait>0` 阻塞等待 |
| **RedLock** | 多 Redis 节点场景，N/2+1 成功视为获取成功 |

### 后端
- **Redis**（生产）
- **LocalMemory**（测试/单机）

---

## 3. utils/reliability — 容错四件套

### 解决的问题
- 第三方 API 抖动拖垮主流程
- 上游故障快速失败（避免雪崩）
- 关键资源并发隔离（避免慢调用占满线程）
- 业务必须有兜底（用户体验底线）

### 核心 API

```python
from utils.reliability import (
    retry, circuit_breaker, bulkhead, fallback
)

# 1. 重试
@retry(max_attempts=3, backoff="exponential", initial_delay=0.1,
       retry_on=(ConnectionError,))
def fetch_data():
    return requests.get("https://api.example.com/data")

# 2. 熔断器
@circuit_breaker(name="payment_api", failure_threshold=5,
                 recovery_time=30, expected_exceptions=(PaymentError,))
def charge_credit_card(order):
    ...

# 3. 隔离舱
@bulkhead(name="email_send", max_concurrent=20, max_wait=5.0)
def send_email(to, subject, body):
    ...

# 4. 降级
@fallback(default=lambda uid: [])
def get_recommendations(uid):
    return call_recommend_service(uid)
```

### 组合使用（生产典型场景）

```python
@fallback(default={"status": "queued"})
@retry(max_attempts=3, backoff="exponential")
@circuit_breaker(name="payment_gw", failure_threshold=10, recovery_time=60)
@bulkhead(name="payment_gw", max_concurrent=50)
def charge(amount, card_no):
    return call_payment_gateway(amount, card_no)
```

**装饰器顺序很重要**：自下而上执行 `bulkhead → cb → retry → fallback`
- bulkhead 先：限制并发入口
- cb 次之：失败计数（每次 retry 算一次失败）
- retry 再次：尝试重试
- fallback 最外：所有重试都失败时兜底

### 状态机

```
                  failure_threshold 连续失败
        ┌──────────────────────────────────────┐
        │                                      ▼
    CLOSED ──────────────────────────────► OPEN
        ▲                                      │
        │ success >= success_threshold         │ recovery_time 到期
        │                                      ▼
        └─────────────── HALF_OPEN ◄──────────┘
```

### 共享状态

熔断器/隔离舱状态通过 `StateStore` 抽象（默认 InMemory，生产用 RedisStateStore）。
切换：`set_state_store(RedisStateStore())`

---

## 4. 实战示例

### 订单支付（完整容错链）

```python
from utils.reliability import retry, circuit_breaker, bulkhead, fallback
from utils.locks import RedisLock
from utils.idempotency import idempotent

class OrderService:
    @fallback(default=lambda order_id, **kw: {"status": "queued"})
    @idempotent(key_fields=["order_id"], ttl=600)
    @retry(max_attempts=3, backoff="exponential", initial_delay=0.1,
           retry_on=(PaymentGatewayError,))
    @circuit_breaker(name="payment_gw", failure_threshold=10, recovery_time=60)
    @bulkhead(name="payment_gw", max_concurrent=50)
    def pay(self, order_id, amount, user_id):
        with RedisLock(f"order:{order_id}:pay", ttl=30, wait=5):
            return self._call_payment_gateway(order_id, amount, user_id)
```

### 业务价值

1. **幂等**：客户端重试不会重复扣款
2. **锁**：保证单订单支付串行
3. **熔断**：网关挂了 10 次就熔断，避免雪崩
4. **重试**：网络抖动时自动恢复
5. **降级**：所有重试都失败时返回「待处理」，用户感知友好
6. **隔离**：网关慢时只影响 50 并发，不影响其他业务

---

## 5. 集成检查清单

- [ ] 生产环境已配置 Redis（`utils.cache.get_redis()` 可用）
- [ ] 业务关键路径已加幂等键（订单/支付/状态变更）
- [ ] 库存/订单并发场景已加分布式锁
- [ ] 外部 API 调用已加重试 + 熔断
- [ ] 用户关键流程有降级（查询接口尤其重要）
- [ ] 已设置 `reliability.set_state_store(RedisStateStore())` 跨进程共享熔断状态

---

## 6. 监控/可观测性（未来扩展）

三个模块都内置 metrics 字典：
- `RedisLock.metrics` — 持锁次数/释放次数/续期次数
- `CircuitBreaker.metrics` — 调用次数/成功/失败/短路/状态切换
- `Bulkhead.metrics` — 调用次数/拒绝/完成

可在管理后台统一展示：失败率、熔断状态变化、隔离舱使用率。
