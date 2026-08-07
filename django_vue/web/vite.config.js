import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    // 注意：5173 已被 D:\Code\wharttest\WHartTest_Vue 的 dev server 长期占用，
    // 本项目固定使用 5273，strictPort 保证端口冲突时直接报错而非静默换端口。
    port: 5273,
    strictPort: true,
    proxy: {
      // 开发期把 API 请求代理到 Django 后端。
      // 注意：8000 端口被多个项目（含 wharttest）的 runserver 同时抢占，
      // 请求会被随机分派导致间歇性失败，故本项目后端固定使用 8300。
      '/api': { target: 'http://127.0.0.1:8300', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8300', changeOrigin: true },
    },
  },
})
