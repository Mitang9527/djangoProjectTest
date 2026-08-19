"""
路由全面审计脚本

用法:
  SECRET_KEY=... JWT_SIGNING_KEY=... API_SECRET_KEY=... \
  .venv/Scripts/python.exe scripts/audit_routes.py

产出:
  1. 完整路由表(应用 / 完整路径 / 视图 / 方法 / 签名状态)
  2. 路径冲突检测(同 path+method 命中多个视图 => real bug)
  3. 签名覆盖范围检查(/api/* 但不在排除列表的接口)
  4. 尝试生成 Swagger schema 以暴露 operationId 冲突
"""
import os
import sys
import django

# 确保项目根在 sys.path(脚本位于 scripts/ 子目录, 运行时该目录才自动入 path)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.test')
django.setup()

from django.urls import get_resolver
from django.conf import settings
from framework.api_signature.middleware import APISignatureMiddleware

# 复用中间件真实匹配逻辑
_mw = APISignatureMiddleware(get_response=lambda r: None)
INCLUDE = _mw.include_paths
EXCLUDE = _mw.exclude_paths


def path_match(path, pattern):
    return _mw._path_match(path, pattern)


def signature_status(path):
    """返回 (in_scope, excluded) 基于真实中间件逻辑"""
    excluded = any(path_match(path, p) for p in EXCLUDE)
    in_scope = any(path_match(path, p) for p in INCLUDE)
    return in_scope, excluded


# ---------- 枚举最终路由 ----------
def method_for_pattern(pat):
    """尽力推断一个 URLPattern 支持的 HTTP 方法"""
    cb = pat.callback
    cls = getattr(cb, 'cls', None)  # DRF @api_view 包装器有 .cls
    view_cls = cls if cls is not None else getattr(cb, 'view_class', None)
    if view_cls is not None:
        # DRF APIView / ViewSet
        base_methods = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}
        methods = []
        for m in view_cls.http_method_names:
            if m not in base_methods:
                continue
            handler = getattr(view_cls, m, None)
            if handler is None:
                continue
            # 判断是否覆写了 APIView 的默认 405 handler
            from rest_framework.views import APIView
            default = getattr(APIView, m, 'NOT_IN_APIVIEW')
            if handler is default:
                continue
            methods.append(m.upper())
        if methods:
            return sorted(methods)
        return [m.upper() for m in view_cls.http_method_names if m in base_methods]
    # 函数视图
    return ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']


def _route_of(pat):
    p = pat.pattern
    return getattr(p, 'route', None) or getattr(p, '_route', '') or ''


def walk(patterns, prefix='', app_hint='', out=None, seen=None):
    if out is None:
        out = []
    if seen is None:
        seen = set()
    for pat in patterns:
        if hasattr(pat, 'url_patterns'):  # URLResolver
            ns = pat.namespace or ''
            sub_app = pat.app_name or ns or app_hint
            walk(pat.url_patterns, prefix + _route_of(pat), sub_app, out, seen)
        else:  # URLPattern
            full = '/' + (prefix + _route_of(pat)).lstrip('/')
            # 规整占位符显示
            full_disp = full.replace('<', '{').replace('>', '}')
            cb = pat.callback
            cls = getattr(cb, 'cls', None) or getattr(cb, 'view_class', None)
            if cls is not None:
                view_name = f"{cls.__module__}.{cls.__name__}"
            elif callable(cb):
                view_name = f"{cb.__module__}.{cb.__qualname__}"
            else:
                view_name = str(cb)
            methods = method_for_pattern(pat)
            # 计算 operationId 风格 key(用于 Swagger 冲突检测)
            name = pat.name or ''
            op_key = f"{name}:{','.join(methods)}" if name else f"{view_name}:{','.join(methods)}"
            entry = {
                'path': full_disp,
                'methods': methods,
                'view': view_name,
                'name': name,
                'namespace': app_hint,
                'op_key': op_key,
            }
            out.append(entry)
    return out


resolver = get_resolver()
all_routes = walk(resolver.url_patterns)

# ---------- 1. 路径+method 冲突 ----------
collisions = {}
for r in all_routes:
    for m in r['methods']:
        key = (r['path'], m)
        collisions.setdefault(key, []).append(r['view'])

print("=" * 110)
print("1. 路由总览 (共 %d 条最终路由)" % len(all_routes))
print("=" * 110)
print(f"{'METHODS':<22}{'PATH':<48}{'SIGN?':<8}VIEW")
print("-" * 110)
for r in sorted(all_routes, key=lambda x: x['path']):
    in_scope, excluded = signature_status(r['path'])
    if in_scope and excluded:
        sign = "排除"
    elif in_scope:
        sign = "需签名"
    else:
        sign = "-"
    print(f"{','.join(r['methods']):<22}{r['path']:<48}{sign:<8}{r['view']}")

# ---------- 2. 冲突 ----------
print("\n" + "=" * 110)
print("2. 路径+方法 冲突检测")
print("=" * 110)
found_collision = False
for (path, method), views in collisions.items():
    uniq = set(views)
    # 过滤框架级"误报": DRF 路由根视图 + Django admin 的同前缀多视图
    uniq_real = {v for v in uniq
                 if 'rest_framework.routers.APIRootView' not in v
                 and v.startswith('django.contrib.admin') is False}
    if len(uniq_real) > 1:
        found_collision = True
        print(f"  [冲突] {method} {path} 命中多个真实视图: {uniq_real}")
if not found_collision:
    print("  ✅ 无真实路径+方法冲突 (DRF 路由根视图 / admin 的同源多视图已忽略)")

# ---------- 3. 签名覆盖 ----------
print("\n" + "=" * 110)
print("3. 签名覆盖范围 (/api/* 但不在排除列表 => 需签名)")
print("=" * 110)
needs_sig = [r for r in all_routes
             if any(path_match(r['path'], p) for p in INCLUDE)
             and not any(path_match(r['path'], p) for p in EXCLUDE)]
print(f"  需签名的接口数: {len(needs_sig)}")

# SPA 影响模拟: 签名中间件在 DRF 鉴权之前运行,
# 因此 JWT Bearer(无 Django session) + Accept: application/json 的请求会在中间件层被拦(403),
# 除非路径在排除列表。下面逐条模拟 "Vue 前端带 JWT 调接口" 的典型请求头。
from django.contrib.auth.models import AnonymousUser


class _FakeReq:
    def __init__(self, accept='application/json', user=None):
        self.META = {'HTTP_ACCEPT': accept}
        self.user = user or AnonymousUser()


spa_blocked = []
for r in sorted(needs_sig, key=lambda x: x['path']):
    # 典型 SPA 请求: JSON Accept + 匿名(无 session, 仅 JWT 在 header, 中间件此时看不到)
    req = _FakeReq()
    in_scope = any(path_match(r['path'], p) for p in INCLUDE)
    excluded = any(path_match(r['path'], p) for p in EXCLUDE)
    would_verify = in_scope and not excluded
    browser_skip = _mw._is_browser_request(req)  # False for JSON+anon
    spa_403 = would_verify and not browser_skip
    if spa_403:
        spa_blocked.append(r)

print(f"\n  ⚠️  其中会被 'Vue 前端(JWT, JSON, 无 session)' 拦截(403) 的接口数: {len(spa_blocked)}")
for r in spa_blocked:
    print(f"    [SPA-403] {','.join(r['methods']):<18}{r['path']:<48}{r['view']}")


# ---------- 4. Swagger operationId 冲突 ----------
print("\n" + "=" * 110)
print("4. Swagger operationId 冲突检测 (尝试生成 schema)")
print("=" * 110)
try:
    from drf_spectacular.generators import SchemaGenerator
    gen = SchemaGenerator()
    schema = gen.get_schema(request=None, public=True)
    # 统计 operationId 重复
    op_ids = {}
    for path, item in schema.get('paths', {}).items():
        for method, op in item.items():
            if method.lower() not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options'):
                continue
            oid = op.get('operationId')
            if oid:
                op_ids.setdefault(oid, []).append(f"{method.upper()} {path}")
    dup = {k: v for k, v in op_ids.items() if len(v) > 1}
    if dup:
        print(f"  ⚠️  发现 {len(dup)} 个重复 operationId (Swagger 会报错/覆盖):")
        for oid, locs in dup.items():
            print(f"    - {oid}: {locs}")
    else:
        print(f"  ✅ schema 生成成功, 无 operationId 冲突 (共 {len(op_ids)} 个 operationId)")
except Exception as e:
    import traceback
    print(f"  ⚠️  schema 生成异常: {type(e).__name__}: {e}")
    traceback.print_exc()

# ---------- 5. resolve() 实证: 被报"冲突"的路径实为 DRF 路由根视图折叠假象 ----------
print("\n" + "=" * 110)
print("5. resolve() 实证 (验证 '冲突' 是否为真实路由冲突)")
print("=" * 110)
from django.urls import resolve
probe = [
    '/saas/api/plans/', '/saas/api/',                 # saas 路由根 + ViewSet 子路径
    '/api/alert_system/rules/', '/api/alert_system/',  # alert_system
    '/api/adb_web/devices/', '/api/adb_web/',          # adb_web
    '/api/users/test/',                                # 用户改动后的测试接口
    '/api/v1/users/test/',
]
for p in probe:
    try:
        m = resolve(p)
        view = m.func.__module__ + '.' + m.func.__qualname__ if hasattr(m.func, '__qualname__') else str(m.func)
        print(f"  resolve('{p}') -> {view}")
    except Exception as e:
        print(f"  resolve('{p}') -> 解析失败: {type(e).__name__}: {e}")
print("  (若 ViewSet 子路径解析到各自 ViewSet、根路径解析到 APIRootView, 则说明无真实冲突)")

print("\n审计完成。")
