#!/usr/bin/env node
// OpenAPI schema 离线导出包装脚本（跨平台，避免 npm script 在 Windows 上
// 直接执行 `../.venv/Scripts/python.exe` 被 cmd 误解析）。
// 优先使用项目 .venv 的 python（系统 Python 缺 pydantic 等依赖），
// 找不到时回退 PATH 中的 python。
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, '..', '..'); // openapi-client/scripts -> 仓库根
const managePy = path.join(projectRoot, 'manage.py');

const venvPython =
  process.platform === 'win32'
    ? path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(projectRoot, '.venv', 'bin', 'python');

const python = existsSync(venvPython) ? venvPython : 'python';
const outFile = path.join(projectRoot, 'openapi-client', 'schema', 'openapi.json');

console.log(`[export-schema] python = ${python}`);
console.log(`[export-schema] manage.py = ${managePy}`);
console.log(`[export-schema] output = ${outFile}`);

const result = spawnSync(
  python,
  [managePy, 'spectacular', '--file', outFile, '--format', 'openapi-json'],
  { stdio: 'inherit' },
);

if (result.error) {
  console.error(`[export-schema] 启动失败: ${result.error.message}`);
  process.exit(1);
}
if (result.status !== 0) {
  console.error(`[export-schema] spectacular 退出码 ${result.status}`);
  process.exit(result.status);
}
console.log(`[export-schema] ✓ schema 已导出 (${outFile})`);
