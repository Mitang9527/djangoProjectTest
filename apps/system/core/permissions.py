"""
API Key 签发权限。
"""
from rest_framework.permissions import BasePermission


class CanIssueApiKey(BasePermission):
    """
    仅平台管理员可签发 API Key。

    决策依据：
    - API Key 是绕过常规会话认证的机器凭证，发放凭证属敏感操作；
    - 原 ``manage.py create_api_key`` 默认以 admin 身份执行，接口侧对齐为管理员专属；
    - 普通用户（非 is_staff）一律禁止，避免凭证被任意自助签发放大攻击面。

    注：调用方必须使用 JWT 认证（见 ApiKeyViewSet.authentication_classes），
    以明确真实操作人；不允许用 API Key 自身来签发新 Key。
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff)


class CanManageApiKey(BasePermission):
    """
    密钥归属人或管理员可管理该密钥的生命周期。

    适用动作：列表 / 详情 / 吊销(停用) / 重新启用 / 轮换 / 删除。
    - 普通用户：仅能查看与操作**自己名下**的密钥；
    - 管理员(is_staff)：可管理全部密钥（含他人名下）。

    注：签发(create) 仍由 ``CanIssueApiKey`` 单独管控（仅管理员，且需 JWT）。
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_staff or obj.user_id == user.id)
        )
