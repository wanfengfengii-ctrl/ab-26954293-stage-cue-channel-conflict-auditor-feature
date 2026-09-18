import { defineConfig } from "@playwright/test";

// 默认打 docker compose 暴露的 web 端口；可用 E2E_BASE_URL 或 WEB_PORT 覆盖
const baseURL =
  process.env.E2E_BASE_URL ?? `http://localhost:${process.env.WEB_PORT ?? 8080}`;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL,
  },
});
