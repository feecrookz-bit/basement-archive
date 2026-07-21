import { test, expect, Page } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://localhost:8080";
const PASSWORD = process.env.E2E_PASSWORD || "e2e-pass";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByTestId("password").fill(PASSWORD);
  await page.getByTestId("signin").click();
  await page.waitForURL("**/");
}

test("unauthenticated visitor is redirected to /login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("password")).toBeVisible();
});

test("wrong password shows an error, right password lands on Live", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("password").fill("not-the-password");
  await page.getByTestId("signin").click();
  await expect(page.getByTestId("login-error")).toBeVisible();

  await page.getByTestId("password").fill(PASSWORD);
  await page.getByTestId("signin").click();
  await page.waitForURL("**/");
  await expect(page.getByText("Regime").first()).toBeVisible();
});

test("Live page renders seeded panels + activity feed", async ({ page }) => {
  await signIn(page);
  // regime
  await expect(page.getByText("TRENDING_UP_EARLY").first()).toBeVisible();
  await expect(page.getByText("PERMITTED").first()).toBeVisible();
  // conviction position card
  await expect(page.getByText("conv 4.38").first()).toBeVisible();
  await expect(page.getByText("×2 confluence").first()).toBeVisible();
  // setup trust self-tuner
  await expect(page.getByText("Setup trust — the ledger self-tuner").first()).toBeVisible();
  // ICT sessions panel
  await expect(page.getByText("Sessions — SOL/USDT").first()).toBeVisible();
  // activity feed from the event bus
  await expect(page.getByTestId("activity-row").first()).toBeVisible();
  // live-refresh chip in the topbar
  await expect(page.getByTestId("refresh-chip")).toBeVisible();
});

test("Ledger shows trades, evidence snapshots and risk vetoes", async ({ page }) => {
  await signIn(page);
  await page.goto("/ledger");
  await expect(page.getByText("SOL/USDT").first()).toBeVisible();
  // evidence expands
  const snap = page.locator("summary", { hasText: "snapshot" }).first();
  await snap.click();
  await expect(page.locator("details[open] pre").first()).toBeVisible();
  // rejected proposal with its reason pill
  await expect(page.getByText("AVAX/USDT").first()).toBeVisible();
  await expect(page.getByText("sector_cap:L1").first()).toBeVisible();
});

test("Performance shows scoreboard and equity curve", async ({ page }) => {
  await signIn(page);
  await page.goto("/performance");
  await expect(page.getByText("Scoreboard").first()).toBeVisible();
  await expect(page.getByText("52.4%").first()).toBeVisible();
  await expect(page.locator("svg path").first()).toBeVisible();
});

test("Config is read-only with version history", async ({ page }) => {
  await signIn(page);
  await page.goto("/config");
  await expect(page.getByText("READ-ONLY").first()).toBeVisible();
  await expect(page.getByText("Version history").first()).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
});

test("API rejects cookieless calls; logout returns to login", async ({ page, request }) => {
  const bare = await request.get(`${API}/api/live`);
  expect(bare.status()).toBe(401);
  const health = await request.get(`${API}/api/health`);
  expect(health.ok()).toBeTruthy(); // health stays open

  await signIn(page);
  await page.getByTestId("logout").click();
  await expect(page).toHaveURL(/\/login/);
});

test("@mobile Live renders without horizontal overflow", async ({ page }) => {
  await signIn(page);
  await expect(page.getByText("Regime").first()).toBeVisible();
  await expect(page.getByText("conv 4.38").first()).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
