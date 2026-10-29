import { expect, test } from "@playwright/test";
import { installPromotionFixture } from "./promotion-fixture";
import { packageSnapshot } from "../src/packages/testFixtures";

for (const theme of ["light", "dark"]) {
  test(`completed cards preview processed media without writes (${theme})`, async ({ page }, info) => {
    await page.addInitScript(value => localStorage.setItem("dojo-theme", value), theme);
    const fixture = await installPromotionFixture(page);
    const writes: string[] = [];
    page.on("request", request => { if (request.method() !== "GET") writes.push(request.url()); });
    const base = packageSnapshot().media[0];
    const artifact = (kind: "original" | "processed", filename: string) => ({
      artifact_ref: `media/${base.media_id}/${kind}.mp4`, kind, filename,
      content_type: "video/mp4", available: true, url: `/api/demo/${kind}`,
      preview_url: "/api/demo/preview",
    });
    await page.route("**/api/demo/photo", route => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640"><rect width="360" height="640" fill="#172b4b"/><circle cx="180" cy="240" r="80" fill="#5195ff"/></svg>' }));
    await page.route("**/api/packages/*-completed", route => route.fulfill({ json: {
      folder_name: "Haftanın antrenmanı-completed", caption: "Test paketi", render_revision: "demo",
      order: ["photo", base.media_id], artifacts: [{ ...artifact("processed", "reel.mp4"), kind: "render" }],
      media: [
        { ...base, filename: "training.mp4", effective_duration: 3, preview_url: "/api/demo/preview", thumbnail_url: "/api/demo/thumbnail", artifacts: [artifact("original", "training.mp4"), artifact("processed", "training.processed.mp4")] },
        { ...base, media_id: "photo", filename: "profile.jpg", content_type: "image/jpeg", processed: { content_type: "image/jpeg" }, effective_duration: 2.95, preview_url: "/api/demo/photo", artifacts: [] },
      ],
    } }));
    await page.goto("/#/completed");
    await expect(page.getByText("Fotoğraf · 2.95 s")).toBeVisible();
    await expect(page.getByRole("img", { name: "training.mp4 önizlemesi" })).toBeVisible();
    expect(await page.locator(".completed-media-grid > li").first().textContent()).toContain("profile.jpg");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const downloads = page.locator(".artifact-links a");
    await expect(downloads).toHaveCount(3);
    for (const link of await downloads.all()) await expect(link).toHaveText("");
    await expect.poll(() => page.locator(".completed-render").evaluate((video: HTMLVideoElement) => video.readyState)).toBeGreaterThanOrEqual(2);
    if (process.env.CAPTURE_COMPLETED) await page.screenshot({ path: `../.impeccable/review/completed-cards-${info.project.name}-${theme}.png`, fullPage: true, animations: "disabled" });
    const trigger = page.getByRole("button", { name: "training.mp4 önizlemesi" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "training.mp4" });
    await expect(dialog.locator("video")).toHaveAttribute("src", "/api/demo/preview");
    await expect.poll(() => dialog.locator("video").evaluate((video: HTMLVideoElement) => video.readyState)).toBeGreaterThanOrEqual(2);
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await page.getByRole("button", { name: "profile.jpg önizlemesi" }).click();
    await expect(page.getByRole("dialog").getByRole("img")).toHaveAttribute("src", "/api/demo/photo");
    expect(writes).toEqual([]);
    expect(fixture.errors).toEqual([]);
  });
}

test("welcome and pairing expose one round floating theme control", async ({ page }, info) => {
  await installPromotionFixture(page, false);
  for (const route of ["welcome", "pair"]) {
    await page.goto(`/#/${route}`);
    const toggle = page.locator(".theme-toggle");
    await expect(toggle).toHaveCount(1);
    await expect(toggle).toHaveText("");
    expect(await toggle.getAttribute("aria-label")).toMatch(/Açık Mod|Koyu Mod/);
    const geometry = await toggle.evaluate(button => {
      const rect = button.getBoundingClientRect(), style = getComputedStyle(button);
      return { position: style.position, radius: style.borderRadius, width: rect.width,
        height: rect.height, right: document.documentElement.clientWidth - rect.right, bottom: innerHeight - rect.bottom };
    });
    expect(geometry).toMatchObject({ position: "fixed", radius: "50%", width: 48, height: 48, bottom: 24 });
    // Native scrollbar gutters reserve extra inline space on desktop.
    expect(geometry.right).toBeGreaterThanOrEqual(24);
    expect(geometry.right).toBeLessThanOrEqual(48);
    await toggle.click();
    if (process.env.CAPTURE_COMPLETED) await page.screenshot({ path: `../.impeccable/review/${route}-floating-${info.project.name}.png`, animations: "disabled" });
  }
});
