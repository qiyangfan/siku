import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  // 桌面壳覆盖两个内核：Windows/Linux(Tauri 用 WebView2/WebKitGTK)，macOS 用 WKWebView
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    // 真实 serve --with-ui：同时验证静态资源挂载与 API 同源行为
    command: "bash e2e/serve-app.sh",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
