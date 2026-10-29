import { expect, test } from "@playwright/test";
import { installPromotionFixture } from "./promotion-fixture";

test("landing sections follow scrolling without changing application routes", async ({ page }, info) => {
  await installPromotionFixture(page, false);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/#/welcome");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Kontrol sende.");
  await page.getByRole("button", { name: "Akışı keşfet", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Tanıtım bölümleri" }).getByRole("button", { name: "Nasıl çalışır?" })).toHaveAttribute("aria-current", "location");
  expect(new URL(page.url()).hash).toBe("#/welcome");
  await page.getByRole("button", { name: "İnceleme adımına geç" }).click();
  await expect(page.locator('[data-anchor="step-2"]')).toBeInViewport();
  if (info.project.name === "desktop") await expect(page.locator(".promotion-stage img")).toHaveAttribute("src", "/promotion/web/review.png");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Aisomedo başlangıç" }).click();
  if (process.env.CAPTURE_PROMOTION) {
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: `../.impeccable/review/promotion-${info.project.name}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: "Uygulamayı aç" }).first().click();
  await expect(page.getByRole("heading", { name: "Tarayıcıyı eşleştir" })).toBeVisible();
});

test("public introduction remains readable without API or animation APIs", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => { Object.defineProperty(window, "IntersectionObserver", { value: undefined }); });
  await page.route(url => url.pathname.startsWith("/api/"), route => route.abort());
  await page.goto("/#/welcome");
  await expect(page.getByRole("heading", { level: 1 }), `Page errors: ${errors.join("; ")}`).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sen onaylamadan yayınlanmaz." })).toBeAttached();
});
