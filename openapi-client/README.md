# OpenAPI Client

由后端 OpenAPI schema 自动生成的前端 TS 类型与 axios 客户端。**generated 产物禁止手改**，接口变更后重新生成即可。

## 使用

```bash
npm install          # 首次安装（依赖锁定见下方"版本铁律"）
npm run generate:api # 一键：导出 schema + 生成客户端
npm run typecheck    # tsc 严格模式校验生成产物类型
```

分步命令：

```bash
npm run export:schema   # 离线导出 schema/openapi.json（内部调 .venv 的 manage.py spectacular）
npm run generate        # openapi-ts 生成 src/generated/
```

## 生成产物

| 路径 | 内容 |
| --- | --- |
| `schema/openapi.json` | 契约快照（入库，接口变更可 diff 追踪） |
| `src/generated/types.gen.ts` | 全部请求/响应/枚举 TS 类型 |
| `src/generated/sdk.gen.ts` | 151 个端点的类型化 axios 函数（如 `v1CorePingRetrieve`） |
| `src/generated/client.gen.ts` | 默认 axios client（baseUrl 默认 `http://127.0.0.1:8300`） |

## 自定义客户端

后端统一返回 CustomRenderer 五字段（`{code, message, data, ...}`），且需要带 Bearer JWT。
用 `@hey-api/client-axios` 的 `createClient()` 加拦截器：

```ts
import { createClient } from '@hey-api/client-axios';
const api = createClient({
  baseUrl: 'http://127.0.0.1:8300',
  interceptors: {
    request: (req) => {
      req.headers.set('Authorization', `Bearer ${localStorage.getItem('token')}`);
      return req;
    },
    // 响应拦截器里解包 data / 统一处理 401
  },
});
// 传给 SDK：v1CorePingRetrieve({ client: api })
```

## 环境变量覆盖

- `OPENAPI_INPUT`：覆盖 schema 输入（如指向联调环境 `http://127.0.0.1:8300/api/schema/`）
- `OPENAPI_OUTPUT`：覆盖输出目录

## 版本铁律（两个坑，勿改）

1. **typescript 必须锁定 6.x**。`@hey-api/openapi-ts@0.99` 自身不声明 typescript 依赖，若宿主装了
   typescript 7（原生 Go 版），生成时崩溃 `Cannot read properties of undefined (reading 'AnyKeyword')`。
   已锁定 `typescript@6.0.3`（与 Fast-Vben-Admin 一致）。升级 typescript 前先验证 `npm run generate`。
2. **input 必须用绝对路径**。openapi-ts >= 0.99 会把两段式相对路径（如 `schema/openapi.json`）误判为
   Hey API shorthand（`org/project`），报 `Invalid Hey API shorthand format`。配置文件里已用
   `path.join(__dirname, 'schema', 'openapi.json')` 兜底，勿改回相对路径。

## 说明

- 后端 Web 端 `/api/schema/` 仅 Admin 可看（AdminRequiredMixin），自动化拉取一律走离线导出（`manage.py spectacular`），无认证/签名问题。
- schema 携带 `servers: http://127.0.0.1:8300`（来自 `SPECTACULAR_SETTINGS['SERVERS']`），生成客户端默认指向该地址。
- 契约变更流程：改后端 serializer/view → `npm run generate:api` → diff 审查 `schema/openapi.json` → 提交。
