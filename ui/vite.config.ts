import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      // 基线（include 全量 src 后）向下取整：
      // 语句 79.94 / 分支 75.58 / 函数 81.31 / 行 79.72。
      thresholds: { statements: 79, branches: 75, functions: 81, lines: 79 },
    },
  },
});
