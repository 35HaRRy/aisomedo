import { test, expect } from "@playwright/test";
import { installPromotionFixture } from "./promotion-fixture";

async function start(page: import("@playwright/test").Page) {
  const server = await installPromotionFixture(page, true, true);
  await page.goto("/#/dashboard");
  return server;
}

test("tours show once, can skip every page and can be replayed from Help", async ({ page }) => {
  const server = await start(page);
  const popover = page.getByRole("dialog", { name: "Kontrol Paneli’ne hoş geldin" });
  await expect(popover).toBeVisible();
  await popover.getByRole("button", { name: "İleri", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Yayın zamanı ve inceleme" })).toBeVisible();
  await page.getByRole("button", { name: "Tüm tanıtımları geç" }).click();
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Kontrol Paneli", exact: true })).toBeVisible();
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await page.getByRole("link", { name: "Güncel Paket", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Güncel Paket", exact: true })).toBeVisible();
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await page.getByText("Yardım", { exact: true }).click();
  await page.getByRole("button", { name: "Tanıtımları yeniden başlat" }).click();
  await expect(page.getByRole("dialog", { name: "Paylaşım Paketi’ni hazırla" })).toBeVisible();
  await expect(page.getByRole("button", { name: "İleri", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "İleri", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Sırala, bölümleri seç, önizle" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await page.getByRole("link", { name: "Etkinlik", exact: true }).click();
  await page.getByRole("link", { name: "Güncel Paket", exact: true }).click();
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  expect(server.errors).toEqual([]);
});

test("route changes and disappearing targets tear down the overlay without mutations", async ({ page }) => {
  await start(page);
  await expect(page.locator(".driver-popover")).toBeVisible();
  await page.evaluate(() => document.querySelector('[data-tour="dashboard-overview"]')?.remove());
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await page.goto("/#/settings");
  await expect(page.locator(".driver-popover")).toBeVisible();
  await page.evaluate(() => { window.location.hash = "#/activity"; });
  await expect(page.locator(".driver-popover")).toHaveCount(0);
});

test("completed steps survive reload, keyboard focus stays in the popup, and product dialogs take priority", async ({ page }, info) => {
  await start(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".driver-popover")).toBeVisible();
  await page.getByRole("button", { name: "İleri", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Yayın zamanı ve inceleme" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Yayın zamanı ve inceleme" })).toBeVisible();
  await page.getByRole("button", { name: "Tüm tanıtımları geç" }).focus();
  await page.keyboard.press("Tab");
  expect(await page.locator(".driver-popover").evaluate(node => node.contains(document.activeElement))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (process.env.CAPTURE_PROMOTION) await page.screenshot({ path: `../.impeccable/review/tour-${info.project.name}.png` });
  await page.evaluate(() => { const dialog = document.createElement("dialog"); dialog.textContent = "Önemli uygulama kararı"; document.body.append(dialog); dialog.showModal(); });
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  await expect(page.getByRole("dialog")).toContainText("Önemli uygulama kararı");
});

test("setup is never covered by promotional tours", async ({ page }) => {
  const server = await installPromotionFixture(page, true, true, false);
  await page.goto("/#/dashboard");
  await expect(page.getByRole("heading", { name: "Instagram bağlantısı", exact: true })).toBeVisible();
  await expect(page.locator(".driver-popover")).toHaveCount(0);
  expect(server.errors).toEqual([]);
});

test("tour tears down if live synchronization is lost", async ({ page }) => {
  await start(page);
  await expect(page.locator(".driver-popover")).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event("fixture:disconnect")));
  await expect(page.locator(".driver-popover")).toHaveCount(0);
});

for (const colorScheme of ["light", "dark"] as const) test(`tour actions and surface have readable ${colorScheme} focus and hover states`, async ({ page }, info) => {
  await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
  await start(page);
  const next = page.getByRole("button", { name: "İleri", exact: true });
  await expect(next).toBeVisible();
  for (const state of ["focus", "hover"] as const) {
    if (state === "focus") await next.focus(); else await next.hover();
    const contrast = await next.evaluate(node => {
      const style = getComputedStyle(node);
      const light = (color: string) => color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(v => {
        const s = v / 255; return s <= .04045 ? s / 12.92 : ((s + .055) / 1.055) ** 2.4;
      }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
      const foreground = light(style.color), background = light(style.backgroundColor);
      return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
    });
    expect(contrast).toBeGreaterThanOrEqual(4.5);
  }
  const surface = await page.locator(".driver-popover").evaluate(node => getComputedStyle(node).backgroundColor);
  expect(surface).toBe(colorScheme === "dark" ? "rgb(16, 24, 39)" : "rgb(255, 255, 255)");
  if (process.env.CAPTURE_PROMOTION) await page.screenshot({ path: `../.impeccable/review/tour-${info.project.name}-${colorScheme}.png` });
});
