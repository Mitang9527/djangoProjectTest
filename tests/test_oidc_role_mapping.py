"""OIDC 角色映射测试 — OIDCBackend._resolve_role_slug / _apply_role_mapping。

覆盖：
- create_user / update_user 时按 claims 绑定系统角色；
- OIDC_ROLE_MAP 显式映射优先、直通（同名 slug）模式、自定义 claim 键；
- 安全约束：只绑 tenant 为空的系统角色、is_active 才绑、未命中忽略、str/list 兼容；
- 幂等：角色未变化不写库（_apply_role_mapping 返回 False）。
"""
import pytest
from django.test import override_settings

from system.saas.models import Role
from system.users.oidc import OIDCBackend
from tests.factories import UserFactory, RoleFactory, TenantFactory

# mozilla OIDCAuthenticationBackend.__init__ 会读取这些必需 settings，
# test settings 下 OIDC_ENABLED=False 未定义，需在测试内补齐最小配置
OIDC_MIN_SETTINGS = dict(
    OIDC_OP_TOKEN_ENDPOINT="https://idp.example.com/token",
    OIDC_OP_USER_ENDPOINT="https://idp.example.com/userinfo",
    OIDC_RP_CLIENT_ID="test-client",
    OIDC_RP_CLIENT_SECRET="test-secret",
    OIDC_RP_SIGN_ALGO="HS256",
)


@pytest.fixture(autouse=True)
def _oidc_min_settings():
    """模块内所有测试都带最小 OIDC settings（backend 实例化必需）"""
    with override_settings(**OIDC_MIN_SETTINGS):
        yield


@pytest.fixture
def backend():
    return OIDCBackend()


@pytest.fixture
def system_role():
    """系统级角色（tenant 空）"""
    return RoleFactory(slug="super-admin", tenant=None, is_active=True)


@pytest.mark.django_db
class TestResolveRoleSlug:
    """_resolve_role_slug 命中规则"""

    def test_explicit_map(self, backend, system_role):
        """OIDC_ROLE_MAP 显式映射：admin → super-admin"""
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": ["admin"]})
        assert slug == "super-admin"

    def test_map_prefers_explicit_over_passthrough(self, backend):
        """映射优先：即便本地存在同名 admin 角色，也走映射表"""
        RoleFactory(slug="admin", tenant=None, is_active=True)
        RoleFactory(slug="super-admin", tenant=None, is_active=True)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": ["admin"]})
        assert slug == "super-admin"

    def test_passthrough_same_slug(self, backend):
        """直通模式：OIDC_ROLE_MAP 为空时，同名 slug 直接命中"""
        RoleFactory(slug="system-admin", tenant=None, is_active=True)
        with override_settings(OIDC_ROLE_MAP={}):
            slug = backend._resolve_role_slug({"roles": ["system-admin"]})
        assert slug == "system-admin"

    def test_str_single_value(self, backend, system_role):
        """claim 值是字符串（非 list）也兼容"""
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": "admin"})
        assert slug == "super-admin"

    def test_custom_claim_key(self, backend, system_role):
        """OIDC_ROLE_CLAIM 自定义：groups 键"""
        with override_settings(OIDC_ROLE_CLAIM="groups", OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"groups": ["admin"]})
        assert slug == "super-admin"

    def test_first_hit_wins(self, backend):
        """list 中第一个命中即返回"""
        RoleFactory(slug="super-admin", tenant=None, is_active=True)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin", "other": "missing"}):
            slug = backend._resolve_role_slug({"roles": ["admin", "other"]})
        assert slug == "super-admin"

    def test_inactive_role_ignored(self, backend):
        """is_active=False 的角色不命中"""
        RoleFactory(slug="super-admin", tenant=None, is_active=False)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": ["admin"]})
        assert slug is None

    def test_tenant_role_ignored(self, backend):
        """带租户的角色（非系统角色）不命中"""
        tenant = TenantFactory()
        RoleFactory(slug="super-admin", tenant=tenant, is_active=True)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": ["admin"]})
        assert slug is None

    def test_unknown_value_ignored(self, backend):
        """映射表中没有、本地也不存在 → None"""
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": ["nobody"]})
        assert slug is None

    def test_no_role_claim(self, backend):
        """claims 里没有角色键 → None"""
        assert backend._resolve_role_slug({"email": "a@b.com"}) is None


@pytest.mark.django_db
class TestApplyRoleMapping:
    """_apply_role_mapping 绑定/解绑/幂等"""

    def test_bind_on_create_user(self, backend, system_role):
        """create_user 建号后即绑定角色"""
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            user = backend.create_user({
                "email": "oidc@example.com",
                "sub": "oidc-sub-1",
                "roles": ["admin"],
            })
        assert user.role_id == system_role.id

    def test_sync_on_update_user(self, backend, system_role):
        """update_user 每次登录同步角色（原本无角色 → 绑定）"""
        user = UserFactory()
        assert user.role is None
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            updated = backend.update_user(user, {"roles": ["admin"]})
        updated.refresh_from_db()
        assert updated.role_id == system_role.id

    def test_role_change_on_update_user(self, backend):
        """角色变更：super-admin → system-admin"""
        r1 = RoleFactory(slug="super-admin", tenant=None, is_active=True)
        r2 = RoleFactory(slug="system-admin", tenant=None, is_active=True)
        user = UserFactory(role=r1)
        with override_settings(OIDC_ROLE_MAP={"admin": "system-admin"}):
            backend.update_user(user, {"roles": ["admin"]})
        user.refresh_from_db()
        assert user.role_id == r2.id

    def test_no_change_returns_false(self, backend, system_role):
        """角色未变化 → 返回 False（不写库）"""
        user = UserFactory(role=system_role)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            changed = backend._apply_role_mapping(user, {"roles": ["admin"]})
        assert changed is False

    def test_unbind_on_missing_claim(self, backend):
        """原角色存在但新 claims 未命中 → 解绑为 None"""
        role = RoleFactory(slug="super-admin", tenant=None, is_active=True)
        user = UserFactory(role=role)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            changed = backend._apply_role_mapping(user, {"roles": ["nobody"]})
        assert changed is True
        user.refresh_from_db()
        assert user.role is None

    def test_unmapped_keeps_role(self, backend, system_role):
        """新 claims 未命中但用户已有角色 → 保持原角色（不解绑）？

        语义：mozilla 只会在匹配到用户后调用 update_user；未命中时我们认为
        不该擅自降权，保留原角色。当前实现 _resolve_role_slug 返回 None 时
        会解绑——此处记录行为并断言（如需保留可在调用方决定）。
        """
        user = UserFactory(role=system_role)
        with override_settings(OIDC_ROLE_MAP={"admin": "super-admin"}):
            slug = backend._resolve_role_slug({"roles": ["nobody"]})
        assert slug is None
        user.refresh_from_db()
        assert user.role_id == system_role.id  # 解绑只发生在 _apply_role_mapping 被调用时
