import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
// 注意：必须用 vitest/config 的 defineConfig，否则配置里的 test 字段类型不合法
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 前端统一走相对路径 /api，由 dev server 代理到后端，避免本地开发的跨域问题
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    include: ["tests/**/*.spec.ts"],
  },
});
