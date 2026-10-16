import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./acceptance", fullyParallel: false, workers: 1, retries: 0,
  timeout: 180000, expect: { timeout: 90000 },
  outputDir: "/evidence/browser",
  reporter: [["list"], ["json", { outputFile: "/evidence/report.json" }]],
  use: { baseURL: process.env.ACCEPTANCE_BASE_URL, browserName: "chromium",
    viewport: { width: 1280, height: 900 }, trace: "retain-on-failure", screenshot: "only-on-failure" },
});
