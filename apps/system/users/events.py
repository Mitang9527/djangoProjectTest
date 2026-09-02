"""用户域领域事件（事务 Outbox 接入）。

事件类型：
  USER_CREATED = "user.created" — 注册成功发布（与用户创建同事务提交），
    消费者：注册成功记录（预留通知 / 欢迎邮件等扩展点）。

接入约定：
  - 发布点：UserRegisterView.create（transaction.atomic 内，业务与事件同提交，
    业务成功则事件必不丢）；payload 含 user_id / username / email / nickname。
  - 消费者注册：UsersConfig.ready() → register_user_event_handlers()，
    模块级 _registered 标志防重（runserver 父子进程 / 测试多次触发安全）。
  - 测试隔离：reset_user_event_handlers() 配合 framework 的 unregister_all_handlers()。
"""
from loguru import logger

from framework.events.publisher import register_handler

# 事件类型常量（对外唯一契约：业务侧发布与消费者注册统一引用）
USER_CREATED = "user.created"

# 消费者名（EventDelivery.target_name 唯一标识，兼作 InboxReceipt 幂等凭证键）
_USER_CREATED_CONSUMER = "user.created.notify"

_registered = False


def _on_user_created(event, payload):
    """注册成功消费者：记录 + 预留通知扩展点。

    幂等由 Outbox 保证（InboxReceipt 存在则重投跳过）；本函数应保持幂等，
    重复执行不产生副作用（不落库、不发外部请求）。
    """
    user_id = payload.get("user_id")
    username = payload.get("username") or ""
    logger.info(
        "[Outbox] 消费 user.created user_id={} username={}",
        user_id, username,
    )
    # 预留扩展点：欢迎邮件 / 新手引导 / 用户画像初始化等异步任务可在此接入。
    # 例：notify_welcome.delay(user_id=user_id, email=payload.get("email"))


def register_user_event_handlers() -> None:
    """注册用户域事件消费者（UsersConfig.ready() 调用，幂等防重）。"""
    global _registered
    if _registered:
        return
    register_handler(
        USER_CREATED,
        _on_user_created,
        consumer_name=_USER_CREATED_CONSUMER,
        consumer_module="system.users.events",
    )
    _registered = True


def reset_user_event_handlers() -> None:
    """重置注册标志（测试隔离用：unregister_all_handlers() 后须重置再注册）。"""
    global _registered
    _registered = False
