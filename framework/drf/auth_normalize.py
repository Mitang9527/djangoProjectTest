"""
Authorization 头自动补全 Bearer 前缀中间件。

痛点
----
手动测试（curl / Apifox / Postman / Bruno）时，拿到 JWT 或 API Key 后必须在前面
手敲 ``Bearer `` 才能通过 DRF 认证——因为项目里 JWTAuthentication、APIKeyAuthentication、
TimedAPIKeyAuthentication 都要求 ``Authorization: Bearer <凭证>`` 形式。漏写 ``Bearer ``
就会得到 401，体验很碎。

本中间件在请求进入 DRF 鉴权之前，对「没有携带任何已知认证方案关键字」的
``Authorization`` 头自动补上 ``Bearer `` 前缀，从而允许直接传裸凭证：

    Authorization: eyJ...      ->  Authorization: Bearer eyJ...     （JWT）
    Authorization: sk-xxx      ->  Authorization: Bearer sk-xxx     （API Key）

安全性与边界
------------
- 本项目鉴权只认 ``Bearer`` 一种方案（JWT / API Key 均走 ``Bearer <凭证>``）。
  仅当头以 ``Bearer `` 开头时才视为「已带方案」原样保留；其余一律当作裸凭证
  补上 ``Bearer `` 前缀。
- 因此 ``Basic`` / ``Digest`` / 任何自定义方案 / 未知字符串都不会被误判为合法
  Bearer 凭证，而是统一补全为 ``Bearer <原值>``——下游认证后端按自身规则裁决
  （无凭据则 401），不会因本中间件而改变鉴权语义。
- ``X-API-Key`` 是独立请求头，本中间件完全不触碰。
- 仅在 ``HTTP_AUTHORIZATION`` 存在且非空时生效；空白头不做处理。
- 仅修改 ``request.META``，DRF 的 ``get_authorization_header`` 读取的就是这个，
  后续所有认证后端（JWT / API Key）自然获得补全后的头。
"""
from __future__ import annotations

import re

# 匹配「<scheme><空白>」形式的方案前缀，例如 "Bearer eyJ..." 中的 "Bearer "。
# 只要头里已存在任意「方案 凭证」结构（Bearer / Basic / 自定义方案均可），
# 就视为已带方案、原样保留；只有「纯裸凭证」（无空格、无方案前缀）才补全 Bearer。
_SCHEME_RE = re.compile(r"^[A-Za-z0-9!#$%&'+\-.^_`|~]+\s+", re.IGNORECASE)


class AuthorizationBearerMiddleware:
    """对裸 token 形式的 Authorization 头自动补全 ``Bearer `` 前缀。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = request.META.get("HTTP_AUTHORIZATION", "")
        if raw and raw.strip():
            # 无方案前缀（纯裸凭证）-> 补全 Bearer；已带「scheme 凭证」-> 不动
            if not _SCHEME_RE.match(raw):
                request.META["HTTP_AUTHORIZATION"] = f"Bearer {raw}"
        return self.get_response(request)
