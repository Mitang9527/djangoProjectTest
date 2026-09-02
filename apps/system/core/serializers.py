from django.utils import timezone
from rest_framework import serializers

from .models import APIKey, AuditLog, DictItem, DictType, FileAsset, LoginLog, Menu, OperationLog


class AuditLogSerializer(serializers.ModelSerializer):
    """
    审计日志序列化器
    """
    user_name = serializers.CharField(source='user.username', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            'id', 'user', 'user_name', 'action', 'action_display', 'log_type',
            'target_model', 'target_id', 'old_data', 'new_data', 'changes',
            'action_info', 'ip_address', 'user_agent', 'request_path',
            'request_method', 'data_hash', 'previous_hash', 'is_tampered', 'created_at',
        )
        read_only_fields = [
            'id', 'data_hash', 'previous_hash', 'is_tampered', 'created_at',
        ]


class LoginLogSerializer(serializers.ModelSerializer):
    """登录日志序列化器（对齐参考 LoginLogPublic）"""
    user_name = serializers.CharField(source='user.username', read_only=True, default='', allow_null=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True, default='', allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = LoginLog
        fields = (
            'id', 'tenant', 'tenant_name', 'user', 'user_name',
            'email', 'ip', 'user_agent', 'status', 'status_display',
            'failure_reason', 'created_at',
        )
        read_only_fields = fields


class OperationLogSerializer(serializers.ModelSerializer):
    """操作日志序列化器（对齐参考 OperationLogPublic）"""
    user_name = serializers.CharField(source='user.username', read_only=True, default='', allow_null=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True, default='', allow_null=True)

    class Meta:
        model = OperationLog
        fields = (
            'id', 'tenant', 'tenant_name', 'user', 'user_name', 'email',
            'module', 'action', 'method', 'path', 'status_code',
            'duration_ms', 'ip', 'user_agent',
            'request_summary', 'response_summary', 'created_at',
        )
        read_only_fields = fields

class SystemStatusSerializer(serializers.Serializer):
    """
    系统状态序列化器
    """
    cpu_usage = serializers.FloatField()
    mem_usage = serializers.FloatField()
    active_users = serializers.IntegerField()
    last_update = serializers.CharField()


class PingSerializer(serializers.Serializer):
    """
    连通性测试 POST 参数校验器
    """
    name = serializers.CharField(max_length=50, help_text="你的名字，将用于回显问候")


class CreateApiKeySerializer(serializers.Serializer):
    """
    签发 API Key 入参校验器（接口版，等价于 manage.py create_api_key）。
    """
    name = serializers.CharField(
        max_length=100,
        help_text="密钥用途标识，例如：报表导出服务",
    )
    owner_username = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="归属用户名；省略则归属当前调用者。仅管理员可指定他人。",
    )
    ttl = serializers.IntegerField(
        required=False,
        default=3600,
        min_value=0,
        help_text="有效秒数；0 表示永不过期",
    )


class ApiKeySerializer(serializers.ModelSerializer):
    """
    API Key 列表 / 详情序列化器。

    安全约束：
    - 绝不输出明文 ``key`` 与 ``key_hash``；
    - ``masked_key`` 仅展示前缀与末 4 位；
    - 可写字段仅 ``name``（改名）与 ``is_active``（吊销 / 重新启用），
      其余字段只读。
    """

    masked_key = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_usable = serializers.SerializerMethodField()
    remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = APIKey
        fields = (
            "id", "name", "masked_key",
            "user_id", "user_username",
            "is_active", "is_expired", "is_usable",
            "expires_at", "last_used_at", "remaining_seconds",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "masked_key", "user_id", "user_username",
            "is_expired", "is_usable", "expires_at", "last_used_at",
            "remaining_seconds", "created_at", "updated_at",
        )

    def get_masked_key(self, obj) -> str:
        return obj.masked_key

    def get_is_expired(self, obj) -> bool:
        return obj.is_expired()

    def get_is_usable(self, obj) -> bool:
        return obj.is_usable()

    def get_remaining_seconds(self, obj) -> int | None:
        if not obj.expires_at:
            return None
        return max(int((obj.expires_at - timezone.now()).total_seconds()), 0)


class DictTypeSerializer(serializers.ModelSerializer):
    """字典类型序列化器（对齐 Fast-Vben-Admin DictionaryTypePublic）"""
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = DictType
        fields = (
            'id', 'name', 'code', 'tenant', 'is_active', 'is_system',
            'remark', 'item_count', 'created_at', 'updated_at',
        )
        # tenant 只读：归属由 perform_create 按当前租户上下文写入，禁客户端指定/迁移
        read_only_fields = ('id', 'tenant', 'is_system', 'created_at', 'updated_at')

    def get_item_count(self, obj) -> int:
        return getattr(obj, 'item_count', None) or obj.items.count()


class DictItemSerializer(serializers.ModelSerializer):
    """字典项序列化器（对齐 Fast-Vben-Admin DictionaryItemPublic）"""
    type_code = serializers.CharField(source='type.code', read_only=True)
    type_name = serializers.CharField(source='type.name', read_only=True)

    class Meta:
        model = DictItem
        fields = (
            'id', 'type', 'type_code', 'type_name', 'tenant',
            'label', 'value', 'sort', 'is_active', 'remark',
            'created_at', 'updated_at',
        )
        # tenant 只读（同 DictType）：归属由 perform_create 按当前租户上下文写入
        read_only_fields = ('id', 'tenant', 'created_at', 'updated_at')


class MenuSerializer(serializers.ModelSerializer):
    """
    平台级菜单序列化器（树形：children 递归展开，供管理端与 my-menus 共用）。

    权限过滤场景（my-menus）下，调用方把过滤后的子树挂在实例的 ``_children``
    属性上，序列化器优先渲染缓存子树，避免 ``obj.children.all()`` 把无权节点带出。
    """
    children = serializers.SerializerMethodField()

    class Meta:
        model = Menu
        fields = (
            'id', 'parent', 'name', 'route_name', 'path', 'component',
            'icon', 'type', 'permission', 'sort', 'is_visible', 'is_active',
            'children', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_children(self, obj):
        cached = getattr(obj, '_children', None)
        if cached is not None:
            if not cached:
                return []
            return MenuSerializer(cached, many=True).data
        children = obj.children.all().order_by('sort', 'created_at')
        if not children:
            return []
        return MenuSerializer(children, many=True).data

    def validate(self, attrs):
        mtype = attrs.get('type', getattr(self.instance, 'type', 'menu') if self.instance else 'menu')
        permission = attrs.get(
            'permission',
            getattr(self.instance, 'permission', '') if self.instance else '',
        )
        if mtype == 'button' and not permission:
            raise serializers.ValidationError({'permission': '按钮类型必须绑定权限码'})
        return attrs


def _human_size(num_bytes: int) -> str:
    """字节数转可读文本（B/KB/MB/GB）。"""
    size = float(num_bytes or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
        size /= 1024
    return f"{num_bytes} B"


class FileAssetSerializer(serializers.ModelSerializer):
    """文件资产序列化器（管理端点 + 配额看板共用）。"""
    tenant_name = serializers.CharField(source='tenant.name', read_only=True, default='', allow_null=True)
    user_name = serializers.CharField(source='user.username', read_only=True, default='', allow_null=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    url = serializers.SerializerMethodField()
    size_display = serializers.SerializerMethodField()

    class Meta:
        model = FileAsset
        fields = (
            'id', 'tenant', 'tenant_name', 'user', 'user_name',
            'category', 'category_display',
            'file_name', 'file_path', 'url', 'file_size', 'size_display',
            'content_type', 'is_deleted', 'created_at',
        )
        read_only_fields = fields

    def get_url(self, obj) -> str:
        # 返回可访问的相对 MEDIA_URL 地址，杜绝绝对路径泄露
        from framework.files.upload import relative_media_url
        return relative_media_url(obj.file_path)

    def get_size_display(self, obj) -> str:
        return _human_size(obj.file_size)
