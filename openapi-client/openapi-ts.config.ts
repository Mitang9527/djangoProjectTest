import { defineConfig } from '@hey-api/openapi-ts';

// OpenAPI → TS 客户端生成配置（参考 Fast-Vben-Admin 的 openapi-ts 链路）
// input 默认读本地离线 schema（Web 端 /api/schema/ 仅 Admin 可见，自动化拉取走离线导出）
// 也可用环境变量覆盖：OPENAPI_INPUT=http://127.0.0.1:8300/api/schema/ OPENAPI_OUTPUT=...
// 注意：openapi-ts >= 0.99 会把两段式相对路径（如 schema/openapi.json）误判为
// Hey API shorthand（org/project），必须用绝对路径或 file:// URL 指向本地 schema。
// 用绝对路径（而非 file:// URL），避免 baseUrl 被推断成 file://。
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const defaultInput = path.join(here, 'schema', 'openapi.json');
export default defineConfig({
  client: '@hey-api/client-axios',
  input: process.env.OPENAPI_INPUT ?? defaultInput,
  output: process.env.OPENAPI_OUTPUT ?? 'src/generated',
  plugins: ['@hey-api/typescript', '@hey-api/sdk'],
});
