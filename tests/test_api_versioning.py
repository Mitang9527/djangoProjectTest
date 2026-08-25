"""
API 版本控制实证测试（URL 路径版本化为唯一权威）。

覆盖矩阵：
1. 默认 settings.API_VERSIONS=['v1'] 时，/api/v2/... 不应挂载（404，证明可配置关闭）。
2. v1 路径在改动后不受影响（仍可解析）。
3. settings.API_VERSIONS 含 'v2' 时，主 urls 挂载的 /api/v2/users/manage/ 解析成功且指向 users_v2 命名空间。
4. discover_app_urls 在 v2 下对「未提供 v2_urls 模块」的 app 优雅跳过，结果集合与 v1 一致。
"""
import importlib

from django.test import TestCase, override_settings
from django.urls import clear_url_caches, resolve, Resolver404
from djangoProjectTest import urls as urls_module
from djangoProjectTest.urls import discover_app_urls


def _reload_urls():
    importlib.reload(urls_module)
    clear_url_caches()


class APIVersioningTest(TestCase):

    def test_v2_disabled_by_default_returns_404(self):
        """默认仅 v1，v2 路径不应存在——证明版本开关可控、无泄漏。"""
        with self.assertRaises(Resolver404):
            resolve('/api/v2/users/manage/')

    def test_v1_paths_still_resolve(self):
        """v1 路径在改动后不受影响（向后兼容）。"""
        r1 = resolve('/api/v1/users/login/')
        self.assertEqual(r1.namespace, 'users')
        r2 = resolve('/api/v1/core/ping/')
        self.assertIsNotNone(r2)

    def test_v2_enabled_mounts_and_resolves(self):
        """启用 v2 后，手动挂载的 /api/v2/users/manage/ 解析成功并指向 users_v2。"""
        with override_settings(API_VERSIONS=['v1', 'v2']):
            _reload_urls()
            try:
                resolver = resolve('/api/v2/users/manage/')
                self.assertEqual(resolver.namespace, 'users_v2')
                self.assertTrue(resolver.view_name.startswith('users_v2:'))
            finally:
                # 还原 URLconf，避免影响其它测试
                _reload_urls()

    def test_discover_app_urls_multi_version_graceful(self):
        """v2 下对缺少 v2_urls 模块的 app 优雅跳过，结果集合应与 v1 完全一致。"""
        with override_settings(API_VERSIONS=['v1', 'v2']):
            v2_set = {str(p.pattern) for p in discover_app_urls()}
        v1_set = {str(p.pattern) for p in discover_app_urls()}
        self.assertEqual(v2_set, v1_set)
        self.assertTrue(any(p.startswith('api/v1/') for p in v1_set))
