"""核心平台基础数据模型。

包含平台级基础设施模型：
- AuditLog / AuditLogArchive   增强版审计日志（含归档与排除模型清单）
- LoginLog / OperationLog      登录日志与操作日志
- APIKey                       平台级 API 密钥（含轮换与过期）
- DictType / DictItem          数据字典（键值配置）
- FileAsset                    文件资产登记
- Menu                         动态菜单（RBAC 权限挂载）
"""

import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.serializers.json import DjangoJSONEncoder
from framework.drf.queryset import TimestampMixin


class AuditLog(models.Model):
    """
    增强版审计日志模型
    """
    ACTION_CHOICES = (
        ('CREATE', '新增'),
        ('UPDATE', '修改'),
        ('DELETE', '删除'),
        ('LOGIN', '登录'),
        ('LOGOUT', '登出'),
        ('LOGIN_FAILED', '登录失败'),
        ('PERMISSION_CHANGE', '权限变更'),
        ('DATA_EXPORT', '数据导出'),
        ('SETTINGS_CHANGE', '配置变更'),
        ('PASSWORD_CHANGE', '密码变更'),
        ('OTHER', '其他'),
    )

    LOG_TYPE_CHOICES = (
        ('MODEL', '模型操作'),
        ('SENSITIVE', '敏感操作'),
        ('SYSTEM', '系统操作'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="操作行为")
    log_type = models.CharField(max_length=10, choices=LOG_TYPE_CHOICES, default='MODEL', verbose_name="日志类型")
    target_model = models.CharField(max_length=100, verbose_name="目标模型", null=True, blank=True)
    target_id = models.CharField(max_length=100, null=True, blank=True, verbose_name="目标ID")
    old_data = models.JSONField(verbose_name="变更前数据", null=True, blank=True, encoder=DjangoJSONEncoder)
    new_data = models.JSONField(verbose_name="变更后数据", null=True, blank=True, encoder=DjangoJSONEncoder)
    changes = models.JSONField(verbose_name="变更详情", null=True, blank=True, encoder=DjangoJSONEncoder)
    action_info = models.JSONField(verbose_name="详细信息", null=True, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField(verbose_name="IP地址", null=True, blank=True)
    user_agent = models.TextField(verbose_name="浏览器指纹", null=True, blank=True)
    request_path = models.CharField(max_length=500, null=True, blank=True, verbose_name="请求路径")
    request_method = models.CharField(max_length=10, null=True, blank=True, verbose_name="请求方法")
    data_hash = models.CharField(max_length=128, verbose_name="数据哈希", null=True, blank=True, db_index=True)
    previous_hash = models.CharField(max_length=128, verbose_name="上一条哈希", null=True, blank=True, db_index=True)
    is_tampered = models.BooleanField(default=False, verbose_name="是否被篡改")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间", db_index=True)

    class Meta:
        db_table = 'core_audit_log'
        verbose_name = '审计日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['target_model', 'target_id']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.target_model or self.log_type}"

    def compute_hash(self):
        """计算当前记录的哈希值"""
        data = {
            'user_id': str(self.user.id) if self.user else None,
            'action': self.action,
            'log_type': self.log_type,
            'target_model': self.target_model,
            'target_id': self.target_id,
            'old_data': self.old_data,
            'new_data': self.new_data,
            'changes': self.changes,
            'action_info': self.action_info,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        data_str = json.dumps(data, sort_keys=True, ensure_ascii=False, cls=DjangoJSONEncoder)
        if self.previous_hash:
            data_str = f"{self.previous_hash}{data_str}"
        return hashlib.sha512(data_str.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """重写 save 方法，自动计算哈希"""
        if not self.data_hash:
            if not self.previous_hash:
                last_log = AuditLog.objects.order_by('-created_at').first()
                if last_log:
                    self.previous_hash = last_log.data_hash
            self.data_hash = self.compute_hash()
        super().save(*args, **kwargs)

    def verify_integrity(self):
        """验证当前记录的完整性"""
        return self.compute_hash() == self.data_hash

    @classmethod
    def verify_chain_integrity(cls):
        """验证整个审计日志链的完整性"""
        logs = cls.objects.order_by('created_at')
        previous_hash = None
        tampered_logs = []
        
        for log in logs:
            if previous_hash and log.previous_hash != previous_hash:
                log.is_tampered = True
                tampered_logs.append(log)
            elif not log.verify_integrity():
                log.is_tampered = True
                tampered_logs.append(log)
            else:
                log.is_tampered = False
            
            previous_hash = log.data_hash
            log.save(update_fields=['is_tampered'])
        
        return tampered_logs


class AuditLogArchive(models.Model):
    """审计日志归档（TTL 清理时的合规保留副本）。

    由 manage.py cleanup_logs 在删除过期 AuditLog 前按批次复制而来，
    字段与 AuditLog 完全一致（含哈希链），另加 archived_at 记录归档时间。
    归档表保留原始历史链，供合规审计/取证查询；在线 AuditLog 在清理后
    级联重置链根，保持在线链自洽可验（verify_chain_integrity）。
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="操作人")
    action = models.CharField(max_length=20, choices=AuditLog.ACTION_CHOICES, verbose_name="操作行为")
    log_type = models.CharField(max_length=10, choices=AuditLog.LOG_TYPE_CHOICES, default='MODEL', verbose_name="日志类型")
    target_model = models.CharField(max_length=100, verbose_name="目标模型", null=True, blank=True)
    target_id = models.CharField(max_length=100, null=True, blank=True, verbose_name="目标ID")
    old_data = models.JSONField(verbose_name="变更前数据", null=True, blank=True, encoder=DjangoJSONEncoder)
    new_data = models.JSONField(verbose_name="变更后数据", null=True, blank=True, encoder=DjangoJSONEncoder)
    changes = models.JSONField(verbose_name="变更详情", null=True, blank=True, encoder=DjangoJSONEncoder)
    action_info = models.JSONField(verbose_name="详细信息", null=True, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField(verbose_name="IP地址", null=True, blank=True)
    user_agent = models.TextField(verbose_name="浏览器指纹", null=True, blank=True)
    request_path = models.CharField(max_length=500, null=True, blank=True, verbose_name="请求路径")
    request_method = models.CharField(max_length=10, null=True, blank=True, verbose_name="请求方法")
    data_hash = models.CharField(max_length=128, verbose_name="数据哈希", null=True, blank=True, db_index=True)
    previous_hash = models.CharField(max_length=128, verbose_name="上一条哈希", null=True, blank=True, db_index=True)
    is_tampered = models.BooleanField(default=False, verbose_name="是否被篡改")
    created_at = models.DateTimeField(verbose_name="操作时间", db_index=True)
    archived_at = models.DateTimeField(auto_now_add=True, verbose_name="归档时间", db_index=True)

    class Meta:
        db_table = 'core_audit_log_archive'
        verbose_name = '审计日志归档'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.target_model or self.log_type}"


class AuditExcludeModel(models.Model):
    """排除审计的模型配置"""
    app_label = models.CharField(max_length=100, verbose_name="应用标签")
    model_name = models.CharField(max_length=100, verbose_name="模型名称")
    exclude_fields = models.JSONField(verbose_name="排除字段", null=True, blank=True, default=list)
    reason = models.TextField(verbose_name="排除原因", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_audit_exclude'
        verbose_name = '审计排除配置'
        verbose_name_plural = verbose_name
        unique_together = ('app_label', 'model_name')

    def __str__(self):
        return f"{self.app_label}.{self.model_name}"


class LoginLog(models.Model):
    """
    登录日志（效仿参考项目 LoginLog，租户级）。

    记录每次登录成功/失败：email / IP / User-Agent / 状态 / 失败原因。
    由登录流程显式写入（record_login_log），列表按租户隔离查询。
    与 AuditLog 的差异：专表、租户级、可被 /logs/login 分页查询；
    AuditLog 仍承担防篡改哈希链的完整审计职责。
    """
    class Status(models.TextChoices):
        SUCCESS = 'success', _('成功')
        FAILED = 'failed', _('失败')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'saas.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='login_logs', verbose_name=_('租户'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='login_logs', verbose_name=_('用户'),
    )
    email = models.CharField(_('邮箱/账号'), max_length=255, blank=True, db_index=True)
    ip = models.CharField(_('IP'), max_length=100, blank=True)
    user_agent = models.CharField(_('User-Agent'), max_length=500, blank=True)
    status = models.CharField(_('状态'), max_length=20, choices=Status.choices, default=Status.SUCCESS, db_index=True)
    failure_reason = models.CharField(_('失败原因'), max_length=255, blank=True)
    created_at = models.DateTimeField(_('登录时间'), auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'core_login_log'
        verbose_name = '登录日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'created_at'], name='idx_loginlog_tenant_created'),
            models.Index(fields=['status', 'created_at'], name='idx_loginlog_status_created'),
        ]

    def __str__(self):
        return f"{self.email} - {self.get_status_display()} - {self.created_at}"


class OperationLog(models.Model):
    """
    操作日志（效仿参考项目 OperationLog，租户级）。

    记录每次写操作（POST/PUT/PATCH/DELETE）的调用方信息与执行结果：
    module / action / method / path / status_code / duration_ms / IP / UA。
    由 OperationLogMiddleware 无侵入写入；列表按租户隔离查询。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'saas.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='operation_logs', verbose_name=_('租户'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='operation_logs', verbose_name=_('用户'),
    )
    email = models.CharField(_('邮箱/账号'), max_length=255, blank=True)
    module = models.CharField(_('模块'), max_length=100, blank=True, db_index=True)
    action = models.CharField(_('动作'), max_length=100, blank=True)
    method = models.CharField(_('请求方法'), max_length=10, blank=True)
    path = models.CharField(_('请求路径'), max_length=500, blank=True, db_index=True)
    status_code = models.IntegerField(_('状态码'), null=True, blank=True)
    duration_ms = models.IntegerField(_('耗时(ms)'), default=0)
    ip = models.CharField(_('IP'), max_length=100, blank=True)
    user_agent = models.CharField(_('User-Agent'), max_length=500, blank=True)
    request_summary = models.TextField(_('请求摘要'), blank=True)
    response_summary = models.TextField(_('响应摘要'), blank=True)
    created_at = models.DateTimeField(_('操作时间'), auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'core_operation_log'
        verbose_name = '操作日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'created_at'], name='idx_oplog_tenant_created'),
            models.Index(fields=['module', 'created_at'], name='idx_oplog_module_created'),
        ]

    def __str__(self):
        return f"{self.method} {self.path} - {self.status_code}"


class APIKey(TimestampMixin, models.Model):
    """
    带时效性的访问密钥（Access Key）。

    用于「先同步校验密钥正确性 + 时效性，再返回受保护信息」的接口：
    - key        明文密钥，仅签发时可见一次，之后不再回显
    - key_hash   SHA256 哈希，用于查询与比对（库内不保留可检索的明文）
    - is_active  是否启用（可主动吊销，无需改密钥）
    - expires_at 过期时间；None 表示永不过期（时效性由签发时 ttl 决定）
    - last_used_at 最近一次成功使用时间
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name="所属用户",
    )
    name = models.CharField(max_length=100, verbose_name="标识用途", help_text="例如：报表导出服务")
    key = models.CharField(
        max_length=128, unique=True,
        verbose_name="明文密钥", help_text="仅签发时可见一次",
    )
    key_hash = models.CharField(
        max_length=64, unique=True, db_index=True,
        verbose_name="SHA256 哈希",
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="最近使用时间")

    class Meta:
        db_table = "core_apikey"
        verbose_name = "访问密钥"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user})"

    def is_expired(self) -> bool:
        """是否已过期（expires_at 非空且已过当前时间）。"""
        return self.expires_at is not None and timezone.now() > self.expires_at

    def is_usable(self) -> bool:
        """当前是否可用：启用且未过期。"""
        return self.is_active and not self.is_expired()

    @property
    def masked_key(self) -> str:
        """
        脱敏展示：保留前缀与末 4 位，中间以 **** 掩码。

        明文密钥仅在签发/轮换时一次性返回；列表与详情一律使用本属性，
        绝不回显明文 ``key`` 字段。
        """
        raw = self.key or ""
        if len(raw) <= 8:
            return "****"
        return f"{raw[:6]}{'*' * 6}{raw[-4:]}"

    @staticmethod
    def hash_key(key: str) -> str:
        """对明文密钥做 SHA256 哈希。"""
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def issue(cls, user, name: str, ttl_seconds: int = None, prefix: str = "sk-") -> "APIKey":
        """
        签发一个带时效性的密钥。

        Args:
            user:        所属用户实例
            name:        用途标识
            ttl_seconds: 有效秒数；None/0 表示永不过期
            prefix:      密钥前缀
        Returns:
            APIKey 实例，实例.key 为明文（仅此处可见一次）
        """
        raw = f"{prefix}{secrets.token_hex(16)}"
        expires_at = None
        if ttl_seconds:
            expires_at = timezone.now() + timedelta(seconds=ttl_seconds)
        return cls.objects.create(
            user=user,
            name=name,
            key=raw,
            key_hash=cls.hash_key(raw),
            expires_at=expires_at,
        )


class DictType(TimestampMixin, models.Model):
    """字典类型（对齐 Fast-Vben-Admin DictionaryType）。

    tenant 为空表示平台全局字典（所有租户可见）；非空表示租户私有字典。
    同一租户内 code 唯一。
    """
    name = models.CharField(max_length=100, verbose_name='字典名称')
    code = models.CharField(max_length=100, verbose_name='字典编码')
    tenant = models.ForeignKey(
        'saas.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='dict_types', verbose_name='所属租户',
    )
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    is_system = models.BooleanField(default=False, verbose_name='系统内置')
    remark = models.CharField(max_length=255, blank=True, verbose_name='备注')

    class Meta:
        verbose_name = '字典类型'
        verbose_name_plural = verbose_name
        ordering = ['-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'code'], name='uq_dict_type_tenant_code'),
        ]

    def __str__(self):
        return f"{self.name}({self.code})"


class DictItem(TimestampMixin, models.Model):
    """字典项（对齐 Fast-Vben-Admin DictionaryItem）。

    tenant 语义同 DictType（空 = 平台全局，所有租户可见）。
    同一租户下 (type, value) 唯一；sort 升序排列。
    """
    type = models.ForeignKey(
        DictType, on_delete=models.CASCADE, related_name='items', verbose_name='字典类型')
    tenant = models.ForeignKey(
        'saas.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='dict_items', verbose_name='所属租户',
    )
    label = models.CharField(max_length=100, verbose_name='显示文本')
    value = models.CharField(max_length=100, verbose_name='字典值')
    sort = models.IntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    remark = models.CharField(max_length=255, blank=True, verbose_name='备注')

    class Meta:
        verbose_name = '字典项'
        verbose_name_plural = verbose_name
        ordering = ['sort', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'type', 'value'], name='uq_dict_item_tenant_type_value'),
        ]

    def __str__(self):
        return f"{self.label}={self.value}"


class FileAsset(TimestampMixin, models.Model):
    """
    文件资产登记表（对齐参考项目 FileAsset）。

    每次上传成功登记一条资产，租户用量统计（usage 的 file_assets / storage_bytes）
    据此计算，使套餐配额 max_file_assets / max_storage_mb 可真实执行。

    统计口径：
    - 一次上传 = 一条资产（登记原始上传文件，压缩/水印/缩略图等派生产物不单独计数）；
    - storage_bytes 统计原始上传大小（Sum(file_size)）。
    """
    class Category(models.TextChoices):
        DOCUMENT = 'document', _('文档')
        IMAGE = 'image', _('图片')
        VIDEO = 'video', _('视频')
        AUDIO = 'audio', _('音频')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'saas.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='file_assets', verbose_name=_('所属租户'),
        help_text=_('空 = 无租户上下文上传（平台级/匿名登记）'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='file_assets', verbose_name=_('上传者'),
    )
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.DOCUMENT, verbose_name=_('资产分类'))
    file_name = models.CharField(max_length=255, verbose_name=_('原始文件名'))
    file_path = models.CharField(max_length=500, db_index=True, verbose_name=_('存储路径'),
                                 help_text=_('MEDIA_ROOT 下的绝对路径（保存产物）'))
    file_size = models.BigIntegerField(default=0, verbose_name=_('文件大小(字节)'))
    content_type = models.CharField(max_length=100, blank=True, verbose_name=_('MIME 类型'))
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name=_('已删除'),
                                     help_text=_('软删标记；统计与配额均排除已删除资产'))

    class Meta:
        verbose_name = _('文件资产')
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'is_deleted'], name='idx_fileasset_tenant_deleted'),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.file_size} B)"


class Menu(TimestampMixin, models.Model):
    """
    平台级动态菜单（对齐 Fast-Vben-Admin 菜单/权限体系）。

    - 树形自引用；type 区分 目录/菜单/按钮；
    - 目录/菜单可绑定权限码（Permission.slug，见 system.saas.permissions.PermissionSlug），
      为空 = 登录可见；非空 = 用户拥有该权限码才可见；
    - 按钮节点供前端按钮级权限（v-permission）使用，权限码必填；
    - 平台级（无 tenant）：全平台共享一套，按用户角色权限过滤下发（my-menus 接口）。
    """
    class Type(models.TextChoices):
        DIRECTORY = 'directory', _('目录')
        MENU = 'menu', _('菜单')
        BUTTON = 'button', _('按钮')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children', verbose_name=_('上级菜单'),
    )
    name = models.CharField(_('名称'), max_length=100)
    route_name = models.CharField(_('路由名'), max_length=100, blank=True)
    path = models.CharField(_('路由路径'), max_length=200, blank=True,
                            help_text='前端路由路径，如 /backend/ai')
    component = models.CharField(_('组件'), max_length=200, blank=True,
                                 help_text='前端组件路径，如 backend/ai')
    icon = models.CharField(_('图标'), max_length=100, blank=True)
    type = models.CharField(_('类型'), max_length=20, choices=Type.choices,
                            default=Type.MENU, db_index=True)
    permission = models.CharField(
        _('权限码'), max_length=100, blank=True, db_index=True,
        help_text='绑定 Permission.slug；目录/菜单为空 = 登录可见，按钮必填',
    )
    sort = models.IntegerField(_('排序'), default=0)
    is_visible = models.BooleanField(_('可见'), default=True)
    is_active = models.BooleanField(_('启用'), default=True)

    class Meta:
        verbose_name = _('菜单')
        verbose_name_plural = verbose_name
        ordering = ['sort', 'created_at']
        indexes = [
            models.Index(fields=['type', 'is_active'], name='idx_menu_type_active'),
        ]

    def __str__(self):
        return self.name
