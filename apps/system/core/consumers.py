"""
WebSocket Consumers - 实时通信处理
"""
import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core.cache import cache
from loguru import logger

User = get_user_model()

# Redis key for tracking online users (sorted set: member=identifier, score=timestamp)
ONLINE_USERS_KEY = 'ws:online_users'
# 用户过期时间（秒）— 超过此时间无心跳则视为离线
ONLINE_USER_TTL = 120


class ChatConsumer(AsyncWebsocketConsumer):
    """
    简单聊天 WebSocket Consumer
    支持：
    - 连接建立
    - 消息收发
    - 群组广播
    """
    
    async def connect(self):
        """连接建立时调用"""
        # 获取房间名（从 URL 参数中获取，默认 public）
        self.room_name = self.scope['url_route']['kwargs'].get('room_name', 'public')
        self.room_group_name = f'chat_{self.room_name}'
        
        logger.info(f"WebSocket 连接: 房间={self.room_name}, 用户={self.scope['user']}")
        
        # 加入房间群组
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': f'欢迎加入房间: {self.room_name}',
            'user': '系统'
        }))
    
    async def disconnect(self, close_code):
        """连接断开时调用"""
        logger.info(f"WebSocket 断开: 房间={self.room_name}, 代码={close_code}")
        
        # 离开房间群组
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """收到消息时调用"""
        try:
            data = json.loads(text_data)
            message = data.get('message', '')
            message_type = data.get('type', 'chat')
            
            # 获取用户名
            username = '匿名用户'
            if self.scope['user'].is_authenticated:
                username = self.scope['user'].username
            
            logger.info("收到消息: 用户={}, 内容={}", username, message)
            
            # 广播消息到群组
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message,
                    'user': username,
                    'message_type': message_type
                }
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"消息解析错误: {e}")
    
    async def chat_message(self, event):
        """处理群组消息"""
        message = event['message']
        username = event['user']
        message_type = event.get('message_type', 'chat')
        
        await self.send(text_data=json.dumps({
            'type': message_type,
            'message': message,
            'user': username
        }))


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    通知推送 WebSocket Consumer
    用于实时推送系统通知给特定用户
    """
    
    async def connect(self):
        """连接建立"""
        if not self.scope['user'].is_authenticated:
            await self.close()
            return
        
        self.user_id = self.scope['user'].id
        self.user_group_name = f'user_{self.user_id}'
        
        logger.info(f"通知通道连接: 用户ID={self.user_id}")
        
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        await self.send(text_data=json.dumps({
            'type': 'system',
            'message': '通知通道已连接',
            'user': '系统'
        }))
    
    async def disconnect(self, close_code):
        """断开连接"""
        if hasattr(self, 'user_group_name'):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """接收客户端消息（可选，主要是服务端推送）"""
        pass
    
    async def send_notification(self, event):
        """发送通知到客户端"""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'title': event.get('title', '通知'),
            'message': event.get('message', ''),
            'data': event.get('data', {})
        }))


class OnlineUsersConsumer(AsyncWebsocketConsumer):
    """
    在线用户统计 WebSocket Consumer
    实时统计和广播当前在线用户数量
    """
    # 在线用户的 channel 名称集合
    channel_group_name = 'online_users'

    async def connect(self):
        """用户连接时"""
        logger.info(f"WebSocket 连接尝试: channel={self.channel_name}")

        # 加入在线用户组
        await self.channel_layer.group_add(
            self.channel_group_name,
            self.channel_name
        )

        await self.accept()
        logger.info(f"WebSocket 连接已接受: channel={self.channel_name}")

        # 生成用户唯一标识（对于未登录用户，使用 channel_name）
        user_identifier = self.get_user_identifier()

        # 添加到 Redis 在线用户集合（sorted set, score=当前时间戳）
        await self._add_online_user(user_identifier)
        current_count = await self._get_online_count()

        logger.info(f"用户上线: {user_identifier}, 当前在线: {current_count}")

        # 立即发送当前在线人数给新连接的用户
        await self.send(text_data=json.dumps({
            'type': 'online_count',
            'count': current_count
        }))

        # 广播当前在线人数给所有用户
        await self.broadcast_online_count()

    async def disconnect(self, close_code):
        """用户断开连接时"""
        user_identifier = self.get_user_identifier()

        # 从 Redis 在线用户集合中移除
        await self._remove_online_user(user_identifier)
        current_count = await self._get_online_count()

        logger.info(f"用户下线: {user_identifier}, 当前在线: {current_count}")

        # 离开在线用户组
        await self.channel_layer.group_discard(
            self.channel_group_name,
            self.channel_name
        )

        # 广播当前在线人数
        await self.broadcast_online_count()

    async def receive(self, text_data):
        """接收客户端消息（主要是心跳）"""
        try:
            data = json.loads(text_data)
            if data.get('type') == 'heartbeat':
                # 刷新用户在线状态（更新 Redis sorted set 中的 score）
                user_identifier = self.get_user_identifier()
                await self._add_online_user(user_identifier)

                # 回复心跳
                await self.send(text_data=json.dumps({
                    'type': 'heartbeat',
                    'status': 'ok'
                }))
        except json.JSONDecodeError:
            pass

    async def broadcast_online_count(self):
        """广播在线用户数到所有连接的客户端"""
        count = await self._get_online_count()
        logger.info(f"广播在线人数: {count}")

        await self.channel_layer.group_send(
            self.channel_group_name,
            {
                'type': 'online_count_update',
                'count': count
            }
        )

    async def online_count_update(self, event):
        """收到在线人数更新时"""
        count = event['count']
        await self.send(text_data=json.dumps({
            'type': 'online_count',
            'count': count
        }))

    def get_user_identifier(self):
        """获取用户唯一标识"""
        if self.scope['user'].is_authenticated:
            return f"user_{self.scope['user'].id}"
        return f"anon_{self.channel_name}"

    # ---- Redis 操作（通过 sync_to_async 包装） ----

    async def _add_online_user(self, identifier: str):
        """将用户加入 Redis sorted set，score 为当前时间戳"""
        import time
        await database_sync_to_async(cache.zadd)(ONLINE_USERS_KEY, {identifier: time.time()})
        # 设置 key 过期时间，防止进程崩溃后残留
        await database_sync_to_async(cache.expire)(ONLINE_USERS_KEY, ONLINE_USER_TTL * 2)

    async def _remove_online_user(self, identifier: str):
        """从 Redis sorted set 中移除用户"""
        await database_sync_to_async(cache.zrem)(ONLINE_USERS_KEY, identifier)

    async def _get_online_count(self) -> int:
        """获取当前在线用户数（清除过期成员后计数）"""
        import time
        cutoff = time.time() - ONLINE_USER_TTL
        # 先清除过期成员
        await database_sync_to_async(cache.zremrangebyscore)(ONLINE_USERS_KEY, 0, cutoff)
        # 计数
        count = await database_sync_to_async(cache.zcard)(ONLINE_USERS_KEY)
        return count or 0
