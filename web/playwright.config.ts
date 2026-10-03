import { defineConfig } from "@playwright/test";
const port = process.env.PLAYWRIGHT_PORT ?? "3000";

export default defineConfig({
  testDir: "./e2e", fullyParallel: true, timeout: 60000,
  use: { baseURL: `http://127.0.0.1:${port}`, browserName: "chromium", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: { command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`, url: `http://127.0.0.1:${port}`, reuseExistingServer: !process.env.CI },
});
