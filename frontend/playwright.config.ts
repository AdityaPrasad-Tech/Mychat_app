import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  expect: { timeout: 15_000 },
  use: {
    ...devices["Desktop Chrome"],
    channel: "chrome",
    launchOptions: { args: ["--no-proxy-server"] },
    baseURL: process.env.MYCHAT_E2E_URL || "http://localhost:3100",
    trace: "retain-on-failure",
  },
});
