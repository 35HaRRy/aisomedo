import { test, expect } from "@playwright/test";
import { client, dashboard, emptyEditor, setupState } from "../src/test/fixtures";
import { installLiveStream } from "./live-fixture";

test("setup widget keeps actions together and adapts optional cards", async ({ page }, info) => {
  await installLiveStream(page);
  const setup = setupState("schedule");
  let branding = { logo_asset: null, caption_template: "Dojo", intro_asset: "branding/assets/" + "a".repeat(32) + ".png", intro_duration: 2, outro_asset: null, outro_duration: null };
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/compat") return route.fulfill({ json: { api_version: "0.1.0" } });
    if (path === "/api/pairing/me") return route.fulfill({ json: client });
    if (path === "/api/setup") return route.fulfill({ json: setup });
    if (path === "/api/dashboard") return route.fulfill({ json: dashboard() });
    if (path === "/api/packages/active/editor") return route.fulfill({ json: emptyEditor() });
    if (path === "/api/media/upload-limits") return route.fulfill({ json: { max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 } });
    if (path === "/api/settings/plan") {
      if (route.request().method() === "PUT") { setup.ready = true; setup.checklist.forEach(item => { if (item.required !== false) item.complete = true; }); }
      return route.fulfill({ json: { anchor_date: "2026-10-26", anchor_time: "18:00", enabled: true, timezone: "Europe/Istanbul" } });
    }
    if (path === "/api/settings/branding") {
      if (route.request().method() === "PATCH") branding = { ...branding, ...route.request().postDataJSON() };
      return route.fulfill({ json: branding });
    }
    if (path.startsWith("/api/settings/branding/assets/")) return route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAO0lEQVR4nO3RsREAMAjDQJMlMmFa9i8zgmjo9AOYO1G3Xzad1fV4YMAfIBMhEyETIRMhEyETIRMhE4V8o/IBKoh0dGEAAAAASUVORK5CYII=", "base64") });
    if (path === "/api/setup/cards/skip") { setup.checklist[6].complete = true; return route.fulfill({ json: setup }); }
    return route.fulfill({ json: {} });
  });
  await page.goto("/#/onboarding");
  const actions = page.getByRole("group", { name: "Kurulum işlemleri" });
  await expect(actions.getByRole("link", { name: "Kuruluma sonra devam et" })).toBeVisible();
  const checkbox = page.getByRole("checkbox", { name: "Düzenli yayını etkinleştir" });
  await expect(checkbox).toBeChecked();
  const aligned = await checkbox.evaluate(input => {
    const box = input.getBoundingClientRect(), label = input.parentElement!.getBoundingClientRect();
    return Math.abs(box.y + box.height / 2 - label.y - label.height / 2) < 2;
  });
  expect(aligned).toBe(true);
  await actions.getByRole("button", { name: "Planı kaydet" }).click();
  await expect(actions.getByRole("link", { name: "Kurulumu bitir" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Kuruluma sonra devam et" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "İsteğe bağlı kartlar" })).toBeVisible();
  await expect(actions.getByRole("button", { name: "Kartları kaydet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Çıkış kartını kaldır" })).toHaveCount(0);
  const cards = page.locator(".optional-card");
  const intro = (await cards.nth(0).boundingBox())!, outro = (await cards.nth(1).boundingBox())!;
  if (info.project.name === "desktop") expect(Math.abs(intro.y - outro.y)).toBeLessThan(2);
  else expect(outro.y).toBeGreaterThan(intro.y + intro.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("onboarding-cards.png"), fullPage: true });
  await page.getByLabel("Giriş süresi (saniye)").fill("3");
  await actions.getByRole("button", { name: "Kartları kaydet" }).click();
  await expect(page.getByRole("heading", { name: "Kurulum tamamlandı" })).toBeVisible();
  expect(branding.intro_duration).toBe(3);
  expect(errors).toEqual([]);
});
