import { defineConfig, devices } from "@playwright/test";

// Services are started externally (CI job / local shell):
//   uvicorn sentinel.api:app --port 8080   (DASHBOARD_PASSWORD set)
//   next start -p 3000                      (web/, after next build)
// Seed the DB first: python scripts/seed_demo.py
// PW_EXECUTABLE lets environments with a preinstalled Chromium skip
// `playwright install` (point it at the chrome binary).
const launchOptions = process.env.PW_EXECUTABLE
  ? { executablePath: process.env.PW_EXECUTABLE }
  : {};

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    screenshot: "only-on-failure",
    launchOptions,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      grepInvert: /@mobile/,
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"] }, // chromium-based mobile profile
      grep: /@mobile/,
    },
  ],
});
