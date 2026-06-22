from rest_framework import permissions

class IsAdminOrSelf(permissions.BasePermission):
    """
    自定义权限：仅允许管理员或用户本人访问/修改数据
    """
    def has_object_permission(self, request, view, obj):
        # 1. 如果是管理员，直接放行
        if getattr(request.user, 'role', 'user') == 'admin' or request.user.is_superuser:
            return True
        
        # 2. 如果是用户本人，允许访问
        # 注意：这里的 obj 应该是 User 实例
        return obj == request.user

class DataPermissionMixin:
    """
    数据权限 Mixin：自动根据用户角色过滤查询集
    """
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # 如果不是管理员，只能看到自己的数据
        if getattr(user, 'role', 'user') != 'admin' and not user.is_superuser:
            return queryset.filter(id=user.id)
            
        return queryset
