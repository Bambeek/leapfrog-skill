// One spec per flow. Roles and labels only, never CSS classes.
// npm i -D @playwright/test @axe-core/playwright
import { test, expect, Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

function guard(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
  page.on("response", (r) => { if (r.status() >= 500) problems.push(`${r.status()} ${r.url()}`); });
  return problems;
}

async function a11y(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test.describe("F01 guest books a meeting", () => {
  test("F01-H1 happy path", async ({ page }) => {
    const problems = guard(page);
    await page.goto("/demo/intro-call");
    await a11y(page);
    await page.getByRole("button", { name: /next available/i }).click();
    await page.getByRole("button", { name: /^\d{1,2}:\d{2}/ }).first().click();
    await page.getByLabel("Name").fill("Ada Example");
    await page.getByLabel("Email").fill("ada@example.test");
    await page.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByRole("heading", { name: /booked/i })).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("F01-E2 double submit books once", async ({ page }) => {
    await page.goto("/demo/intro-call");
    await page.getByRole("button", { name: /^\d{1,2}:\d{2}/ }).first().click();
    await page.getByLabel("Name").fill("Ada Example");
    await page.getByLabel("Email").fill("ada@example.test");
    const confirm = page.getByRole("button", { name: "Confirm" });
    await Promise.all([confirm.click(), confirm.click({ force: true }).catch(() => {})]);
    await expect(page.getByRole("heading", { name: /booked/i })).toHaveCount(1);
  });
});
