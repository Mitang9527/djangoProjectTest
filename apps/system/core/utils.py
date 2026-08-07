"""
WebSocket 通知工具函数
"""
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from loguru import logger


def send_user_notification(user_id, title, message, data=None):
    """
    向指定用户发送实时通知
    
    Args:
        user_id: 用户 ID
        title: 通知标题
        message: 通知内容
        data: 附加数据（可选）
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'user_{user_id}',
                {
                    'type': 'send_notification',
                    'title': title,
                    'message': message,
                    'data': data or {}
                }
            )
            logger.info(f"通知已发送: 用户ID={user_id}, 标题={title}")
            return True
    except Exception as e:
        logger.error(f"发送通知失败: {e}")
    return False


def send_room_message(room_name, message, username='系统'):
    """
    向指定聊天室发送消息
    
    Args:
        room_name: 房间名称
        message: 消息内容
        username: 发送者用户名
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'chat_{room_name}',
                {
                    'type': 'chat_message',
                    'message': message,
                    'user': username,
                    'message_type': 'chat'
                }
            )
            logger.info(f"消息已发送: 房间={room_name}, 用户={username}")
            return True
    except Exception as e:
        logger.error(f"发送聊天室消息失败: {e}")
    return False
