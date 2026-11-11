---
name: naki-e2e-playwright
description: End-to-end tests with Playwright: test structure, page objects, stable role-based locators, web-first assertions, authenticated storage state, test data, flaky test diagnosis, traces and CI artifacts. Use when writing or fixing Playwright tests, setting up e2e in CI, or when an e2e suite is slow or flaky.
---

# E2E with Playwright

E2E tests prove that critical user journeys work in a real browser against a running app. Keep them few
and valuable; push detail down to `naki-frontend-testing` and API tests. Follow the project rules skill
if the project has one (for example `naki-myapp`).

## When to use

- Covering a critical flow: sign in, create/edit/delete a core record, checkout, permission boundaries.
- Adding Playwright to a project or to CI.
- A test passes locally and fails in CI, or fails one run in ten.

## Core rules

1. **Locate by role and accessible name.** `page.getByRole("button", { name: "Save" })`, `getByLabel`,
   `getByText`. Use `getByTestId` when there is no accessible handle. Never CSS chains or XPath tied to layout.
2. **Use web-first assertions** (`await expect(locator).toBeVisible()`, `toHaveText`, `toHaveURL`).
   They retry until timeout. Do not read a value and assert on it synchronously.
3. **Never `waitForTimeout`.** Wait for a condition: an element, a URL, a network response.
4. **Each test is independent.** It creates its own data (via API or fixtures) and does not rely on another
   test running first.
5. **Authenticate once, reuse storage state.** A setup project logs in and saves `storageState`; tests load it.
6. **Seed through the API, assert through the UI.** UI-driven setup is slow and multiplies flakiness.
7. **Page objects hold locators and actions, tests hold assertions.** Keep page objects thin.
8. **Collect evidence on failure:** trace on first retry, screenshot and video on failure.
9. **Retries are a diagnostic, not a fix.** A test that needs a retry is flaky; record it and fix the cause.
10. **Do not test third-party sites.** Mock or stub external services with `page.route`.

## Layout

```
e2e/
  auth.setup.ts        # logs in, writes .auth/user.json
  fixtures.ts          # custom fixtures (api client, seeded data)
  pages/
    alerts-page.ts
  alerts.spec.ts
playwright.config.ts
```

Add `.auth/` to `.gitignore`. Storage state contains session cookies.

## Config essentials

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["github"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "chromium", use: { ...devices["Desktop Chrome"], storageState: ".auth/user.json" },
      dependencies: ["setup"] },
  ],
  webServer: { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: !process.env.CI },
});
```

## Example: page object and test

```ts
// e2e/pages/alerts-page.ts
import type { Page } from "@playwright/test";

export class AlertsPage {
  constructor(private readonly page: Page) {}
  readonly search = () => this.page.getByRole("searchbox", { name: "Search alerts" });
  row = (title: string) => this.page.getByRole("row").filter({ hasText: title });
  async goto() { await this.page.goto("/alerts"); }
  async close(title: string) {
    await this.row(title).getByRole("button", { name: "Close alert" }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: "Confirm" }).click();
  }
}
```

```ts
// e2e/alerts.spec.ts
import { test, expect } from "./fixtures";
import { AlertsPage } from "./pages/alerts-page";

test("analyst closes an alert", async ({ page, seedAlert }) => {
  const alert = await seedAlert({ title: `Suspicious login ${Date.now()}` });
  const alerts = new AlertsPage(page);
  await alerts.goto();
  await alerts.close(alert.title);
  await expect(alerts.row(alert.title)).toContainText("Closed");
});
```

Unique titles (`Date.now()` or a random suffix) keep parallel workers from colliding.

## Diagnosing flaky tests

1. Reproduce: `npx playwright test alerts.spec.ts --repeat-each=20 --workers=4`.
2. Open the trace: `npx playwright show-trace test-results/<test>/trace.zip`. Check the action timeline,
   network and console.
3. Classify the cause:

| Symptom | Usual cause | Fix |
|---|---|---|
| element not found intermittently | asserting before data loads | web-first assertion on the loaded state |
| click does nothing | element re-rendered or covered by overlay | wait for overlay to disappear, locate after render |
| passes alone, fails in parallel | shared data or account | per-test data, unique names |
| fails only in CI | slower machine, different timezone/locale | condition waits, set `locale`/`timezoneId` in config |
| strict mode violation | locator matches several elements | narrow with `filter`, `within`, or exact name |

4. Fix the cause, run `--repeat-each` again, then remove any temporary `test.fixme` or retries you added.

## CI

- Install browsers with `npx playwright install --with-deps chromium` (cache the browser directory).
- Upload `playwright-report/` and `test-results/` as artifacts on failure.
- Run against a freshly built app, not the dev server, when possible.
- Never point e2e at production data. Use a dedicated test environment and test accounts.

## Checklist

- [ ] Locators are role, label or test id based.
- [ ] No `waitForTimeout`, no manual sleeps.
- [ ] Tests create their own data and clean up or use unique values.
- [ ] Auth via storage state; `.auth/` ignored by git.
- [ ] Trace, screenshot and video configured for failures.
- [ ] Suite passes with `--repeat-each` on changed tests.

## Common mistakes

| Mistake | Fix |
|---|---|
| `page.locator("div.card > span:nth-child(2)")` | role or text locator |
| `expect(await el.textContent()).toBe("x")` | `await expect(el).toHaveText("x")` |
| Logging in through the UI in every test | storage state from a setup project |
| One long test covering ten features | one journey per test |
| Raising global timeout to hide slowness | find the slow step in the trace |
