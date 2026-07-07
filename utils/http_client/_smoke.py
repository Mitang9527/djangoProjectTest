# sync-init: skip
# -*- coding: utf-8 -*-
"""HTTPClient smoke tests with mocked requests.Session.
Usage:  python -m utils.http_client._smoke
"""
import requests
from unittest.mock import patch

from utils.http_client import (
    HTTPClient, StatusError, TimeoutError, ConnectionError_,
    RetryExhaustedError, LoggingInterceptor, TimingInterceptor, AuthInterceptor,
    get_default_client, set_default_client, close_default_client,
)


def make_response(status, body=b'{"ok": true}', headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = body
    r.headers.update(headers or {"Content-Type": "application/json"})
    r.url = "http://mock/x"
    r.request = requests.Request("GET", "http://mock/x").prepare()
    return r


# ============================================================
# T1: 基本 GET + 默认 timeout
# ============================================================
client = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[])
client._session.mount("http://", requests.adapters.HTTPAdapter())
with patch.object(client._session, "request", return_value=make_response(200, b'{"x":1}')) as m:
    r = client.get("/x")
    assert r.status_code == 200
    assert r.json() == {"x": 1}
    assert m.call_args.kwargs["timeout"] == (5, 30)
print("T1 OK  basic GET + json + default timeout")

# ============================================================
# T2: POST json
# ============================================================
with patch.object(client._session, "request", return_value=make_response(201, b'{"id":1}')) as m:
    r = client.post("/users", json={"name": "X"})
    assert m.call_args.kwargs["json"] == {"name": "X"}
    assert r.status_code == 201
print("T2 OK  POST + json body")

# ============================================================
# T3: 非 2xx 抛 StatusError
# ============================================================
with patch.object(client._session, "request", return_value=make_response(404, b'not found')):
    try:
        client.get("/missing")
    except StatusError as e:
        assert e.status_code == 404
        assert e.method == "GET"
        assert e.url == "http://mock/missing"
        assert e.body == "not found"
print("T3 OK  StatusError raised with attrs")

# ============================================================
# T4: raise_for_status=False 不抛
# ============================================================
client2 = HTTPClient(base_url="http://mock", max_retries=0, raise_for_status=False, interceptors=[])
with patch.object(client2._session, "request", return_value=make_response(500)):
    r = client2.get("/err")
    assert r.status_code == 500
print("T4 OK  raise_for_status=False returns response")

# ============================================================
# T5: 重试 5xx 成功
# ============================================================
calls = [make_response(503, b''), make_response(200, b'{"ok":1}')]
def side_effect_ok(*a, **kw):
    return calls.pop(0)
client3 = HTTPClient(base_url="http://mock", max_retries=2, backoff_factor=0.001, interceptors=[])
with patch.object(client3._session, "request", side_effect=side_effect_ok):
    r = client3.get("/retry")
    assert r.status_code == 200
print("T5 OK  5xx retry succeeds on 2nd attempt")

# ============================================================
# T6: 重试耗尽
# ============================================================
client4 = HTTPClient(base_url="http://mock", max_retries=2, backoff_factor=0.001, interceptors=[])
with patch.object(client4._session, "request", return_value=make_response(503)):
    try:
        client4.get("/x")
    except RetryExhaustedError as e:
        assert e.attempts == 3
        assert isinstance(e.last_error, StatusError)
        assert e.last_error.status_code == 503
print("T6 OK  RetryExhaustedError after N attempts")

# ============================================================
# T7: 拦截器改写 kwargs
# ============================================================
class AddHeader:
    def before_request(self, method, url, **kw):
        h = dict(kw.get("headers") or {})
        h["X-Injected"] = "yes"
        kw["headers"] = h
        return kw
    def after_response(self, *a, **kw): pass
    def on_error(self, *a, **kw): pass

client5 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[AddHeader()])
with patch.object(client5._session, "request", return_value=make_response(200)) as m:
    client5.get("/x")
    assert m.call_args.kwargs["headers"]["X-Injected"] == "yes"
print("T7 OK  interceptor before_request injects headers")

# ============================================================
# T8: 拦截器链式改写
# ============================================================
class Append1:
    def before_request(self, method, url, **kw):
        kw["headers"] = {**(kw.get("headers") or {}), "X-Step": "1"}
        return kw
    def after_response(self, *a, **kw): pass
    def on_error(self, *a, **kw): pass
class Append2:
    def before_request(self, method, url, **kw):
        kw["headers"] = {**(kw.get("headers") or {}), "X-Step2": "2"}
        return kw
    def after_response(self, *a, **kw): pass
    def on_error(self, *a, **kw): pass

client6 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[Append1(), Append2()])
with patch.object(client6._session, "request", return_value=make_response(200)) as m:
    client6.get("/x")
    assert m.call_args.kwargs["headers"]["X-Step"] == "1"
    assert m.call_args.kwargs["headers"]["X-Step2"] == "2"
print("T8 OK  interceptor chain overrides kw in order")

# ============================================================
# T9: AuthInterceptor
# ============================================================
token_called = []
def tok():
    token_called.append(1)
    return "secret-token-123"

client7 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[AuthInterceptor(tok)])
with patch.object(client7._session, "request", return_value=make_response(200)) as m:
    client7.get("/x")
    assert m.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-token-123"
    assert len(token_called) == 1
print("T9 OK  AuthInterceptor adds Bearer token")

# ============================================================
# T10: AuthInterceptor token_getter 抛错不重抛
# ============================================================
def bad_tok():
    raise RuntimeError("expired")

client8 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[AuthInterceptor(bad_tok)])
with patch.object(client8._session, "request", return_value=make_response(200)) as m:
    r = client8.get("/x")
    # token_getter 抛错时, 不应注入 Authorization（headers 可能为 None 或 dict）
    h = m.call_args.kwargs.get("headers") or {}
    assert "Authorization" not in h
print("T10 OK AuthInterceptor swallows getter exception")

# ============================================================
# T11: LoggingInterceptor 注入 trace_id
# ============================================================
li = LoggingInterceptor()
out = li.before_request("GET", "http://x", headers={})
assert "X-Trace-Id" in out["headers"]
out2 = li.before_request("GET", "http://x", headers={"X-Trace-Id": "my-id"})
assert out2["headers"]["X-Trace-Id"] == "my-id"
print("T11 OK LoggingInterceptor injects X-Trace-Id")

# ============================================================
# T12: TimingInterceptor 统计
# ============================================================
ti = TimingInterceptor()
ti.after_response("GET", "http://x", make_response(200), 12.3)
ti.after_response("GET", "http://x", make_response(200), 7.7)
ti.on_error("GET", "http://x", ConnectionError_("net"), 5.0)
assert ti.count == 3
assert 7.0 < ti.avg_ms() < 9.0  # (12.3+7.7+5.0)/3 ≈ 8.33
print(f"T12 OK TimingInterceptor stats: count={ti.count} avg={ti.avg_ms():.1f}ms")

# ============================================================
# T13: 超时包装
# ============================================================
client9 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[])
with patch.object(client9._session, "request", side_effect=requests.Timeout("slow")):
    try:
        client9.get("/x")
    except TimeoutError as e:
        assert "slow" in str(e)
print("T13 OK TimeoutError raised")

# ============================================================
# T14: 连接错误包装
# ============================================================
client10 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[])
with patch.object(client10._session, "request", side_effect=requests.ConnectionError("dns")):
    try:
        client10.get("/x")
    except ConnectionError_ as e:
        assert "dns" in str(e)
print("T14 OK ConnectionError_ raised")

# ============================================================
# T15: context manager
# ============================================================
with HTTPClient(base_url="http://x", max_retries=0, interceptors=[]) as c:
    with patch.object(c._session, "request", return_value=make_response(200)):
        r = c.get("/x")
        assert r.status_code == 200
print("T15 OK context manager works")

# ============================================================
# T16: add_interceptor 链式
# ============================================================
client11 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[])
# 默认拦截器 = 1 个 LoggingInterceptor；add 1 个 = 2 个
client11.add_interceptor(Append1())
assert len(client11.interceptors) == 2
print("T16 OK add_interceptor chainable")

# ============================================================
# T17: URL 拼接
# ============================================================
c = HTTPClient(base_url="https://api.example.com", max_retries=0, interceptors=[])
assert c._build_url("/users") == "https://api.example.com/users"
assert c._build_url("users") == "https://api.example.com/users"
assert c._build_url("https://other.com/x") == "https://other.com/x"
assert c._build_url("") == "https://api.example.com"
c2 = HTTPClient(max_retries=0, interceptors=[])
assert c2._build_url("/x") == "/x"
print("T17 OK URL building")

# ============================================================
# T18: 全局 default client
# ============================================================
c = get_default_client()
assert isinstance(c, HTTPClient)
c2 = get_default_client()
assert c is c2
set_default_client(HTTPClient(base_url="http://custom", interceptors=[]))
c3 = get_default_client()
assert c3.base_url == "http://custom"
close_default_client()
print("T18 OK default client singleton")

# ============================================================
# T19: headers 默认合并到 session.headers
# ============================================================
client12 = HTTPClient(base_url="http://mock", max_retries=0, interceptors=[],
                      headers={"X-Default": "yes"})
# 默认 headers 注入到 session.headers
assert client12.session.headers.get("X-Default") == "yes"
with patch.object(client12._session, "request", return_value=make_response(200)) as m:
    client12.get("/x", headers={"X-Call": "z"})
    # 单次请求带了自己的 headers
    h = m.call_args.kwargs.get("headers") or {}
    assert h.get("X-Call") == "z"
print("T19 OK default headers merged via session.headers")

# ============================================================
# T20: 4xx 不重试
# ============================================================
client13 = HTTPClient(base_url="http://mock", max_retries=3, backoff_factor=0.001, interceptors=[])
call_count = [0]
def se(*a, **kw):
    call_count[0] += 1
    return make_response(400)
with patch.object(client13._session, "request", side_effect=se):
    try:
        client13.get("/x")
    except StatusError as e:
        assert e.status_code == 400
assert call_count[0] == 1, f"4xx should not retry, got {call_count[0]}"
print(f"T20 OK 4xx not retried (calls={call_count[0]})")

print("\nAll 20 tests passed.")
