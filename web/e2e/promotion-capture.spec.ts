import { test, expect } from "@playwright/test";
import { installPromotionFixture } from "./promotion-fixture";

test("promotion captures show real application views with controlled sample data", async ({ page }, info) => {
  const server = await installPromotionFixture(page);
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  const views = [
    ["dashboard", "dashboard", "Kontrol Paneli"],
    ["package", "package", "Güncel Paket"],
    ["sections", "package", "Güncel Paket"],
    ["review", "package?review=2", "Yayın İncelemesi"],
    ["completed", "completed", "Tamamlanmış paketler"],
    ["setup", "onboarding", "Kurulum tamamlandı"],
  ];
  for (const [name, route, heading] of views) {
    await page.goto(`/#/${route}`);
    await expect(page.getByRole("heading", { name: heading, exact: true, level: 1 })).toBeVisible();
    if (name === "sections") await page.getByRole("button", { name: "Antrenman.mp4 bölümlerini düzenle" }).click();
    if (name === "completed") await expect(page.getByRole("heading", { name: "Haftanın antrenmanı-completed", exact: true })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect.poll(() => page.locator("video").evaluateAll(nodes => nodes.every(node => node.readyState >= 2))).toBe(true);
    if (name === "package") {
      const duration = await page.locator("video").first().evaluate((node: HTMLVideoElement) => node.duration);
      await expect(page.getByRole("heading", { name: `Kaydedilmiş Reel önizlemesi · ${duration.toFixed(2)} s`, exact: true })).toBeVisible();
    }
    if (name === "review") {
      const chronology = await page.evaluate(async () => {
        const data = await (await fetch("/api/dashboard")).json();
        const detail = await (await fetch("/api/reviews/2")).json();
        return { created: Date.parse(data.package.created_at), reviewed: Date.parse(detail.review.created_at) };
      });
      expect(chronology.reviewed).toBeGreaterThanOrEqual(chronology.created);
    }
    for (const video of await page.locator("video").all()) {
      await video.evaluate(async (node: HTMLVideoElement) => {
        node.muted = true;
        node.pause();
        if (node.duration > 0) await new Promise<void>(resolve => {
          node.addEventListener("seeked", () => resolve(), { once: true });
          node.currentTime = Math.min(1, node.duration / 2);
        });
        await node.play();
        await new Promise<void>(resolve => node.requestVideoFrameCallback(() => resolve()));
        node.pause();
      });
    }
    if (process.env.CAPTURE_PROMOTION && info.project.name === "desktop") {
      await page.screenshot({ path: `public/promotion/web/${name}.png`, fullPage: true });
    }
  }
  expect(server.errors).toEqual([]);
});
