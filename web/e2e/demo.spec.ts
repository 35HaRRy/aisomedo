import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

async function watchIsolation(page: Page) {
  const leaks: string[] = [], errors: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") || url.protocol.startsWith("http") && url.origin !== new URL(page.url() === "about:blank" ? request.url() : page.url()).origin) leaks.push(request.url());
  });
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem("real-record-sentinel", "preserved");
    document.cookie = "old_session=opaque; SameSite=Lax";
    const open = indexedDB.open.bind(indexedDB);
    Object.assign(window, { demoIdbOpens: 0 });
    indexedDB.open = (...args: Parameters<IDBFactory["open"]>) => {
      Object.assign(window, { demoIdbOpens: Number(Reflect.get(window, "demoIdbOpens")) + 1 }); return open(...args);
    };
  });
  return async () => {
    expect(leaks).toEqual([]); expect(errors).toEqual([]);
    expect(await page.evaluate(() => Reflect.get(window, "demoIdbOpens"))).toBe(0);
    expect(await page.evaluate(() => ({ ...localStorage }))).toEqual({ "real-record-sentinel": "preserved" });
  };
}
async function ready(page: Page) {
  await expect(page.getByRole("heading", { name: "Kontrol Paneli" })).toBeVisible();
  await expect(page.locator(".demo-badge")).toHaveText("demo");
  await page.getByRole("button", { name: "Tüm tanıtımları geç" }).click();
  await expect(page.locator(".live-content")).toBeEnabled();
}

test("welcome link, settings, completed media, reset, and layout stay isolated", async ({ page }, info) => {
  const verify = await watchIsolation(page);
  await page.goto("/#/welcome");
  await page.getByRole("link", { name: "Demo", exact: true }).click();
  await ready(page);
  await page.screenshot({ path: `../.impeccable/review/demo-${info.project.name}.png`, fullPage: true });
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await page.getByRole("button", { name: /Açıklama şablonu/ }).click();
  await page.getByLabel("Açıklama şablonu", { exact: true }).fill("Tarayıcı demo taslağı");
  await page.getByRole("button", { name: "Açıklamayı kaydet" }).click();
  await expect(page.getByText("Ayarlar kaydedildi.", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Etkinlik", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Etkinlik", exact: true })).toBeVisible();
  for (const href of await page.locator('a[href^="#/"]').evaluateAll(links => links.map(link => link.getAttribute("href")))) expect(href).toMatch(/^#\/demo\//);
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await page.getByRole("button", { name: /Açıklama şablonu/ }).click();
  await expect(page.getByLabel("Açıklama şablonu", { exact: true })).toHaveValue("Tarayıcı demo taslağı");
  await page.getByRole("link", { name: "Tamamlanmış paketler", exact: true }).click();
  await expect(page.getByLabel("Tamamlanmış paket seç").locator("option")).toHaveCount(2);
  await expect.poll(() => page.locator("video").first().evaluate(video => (video as HTMLVideoElement).readyState)).toBeGreaterThan(0);
  for (const href of await page.locator(".artifact-links a").evaluateAll(links => links.map(link => link.getAttribute("href")))) expect(href).toMatch(/^\/demo\//);
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await page.getByRole("button", { name: /İsteğe bağlı kartlar/ }).click();
  await page.getByLabel("Giriş görseli", { exact: true }).setInputFiles(fileURLToPath(new URL("../public/demo/training.webm", import.meta.url)));
  await page.getByRole("button", { name: "Kartları kaydet" }).click();
  await expect(page.getByText("Ayarlar kaydedildi.", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Etkinlik", exact: true }).click();
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await page.getByRole("button", { name: /İsteğe bağlı kartlar/ }).click();
  await expect(page.locator('video[aria-label="Giriş kartı önizlemesi"]')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await verify();
  await page.goto("/#/demo/settings");
  await page.reload();
  await page.getByRole("button", { name: /Açıklama şablonu/ }).click();
  await expect(page.getByLabel("Açıklama şablonu", { exact: true })).not.toHaveValue("Tarayıcı demo taslağı");
  await verify();
});

test("local upload conflict, render, Instagram simulation, and pairing exit send nothing", async ({ page }) => {
  const verify = await watchIsolation(page); let popups = 0;
  page.on("popup", () => { popups++; });
  await page.goto("/#/demo/dashboard"); await ready(page);
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await page.getByRole("button", { name: /Instagram bağlantısı/ }).click();
  await page.getByRole("button", { name: "Instagram ile yetkilendir" }).click();
  await page.getByRole("button", { name: "@ornek_studyo_demo_2 hesabını seç" }).click();
  await expect(page.getByText(/@ornek_studyo_demo_2 ·/)).toBeVisible(); expect(popups).toBe(0);
  await page.getByRole("link", { name: "Güncel Paket", exact: true }).click();
  await page.getByRole("button", { name: "Fotoğraf ve video yükle panelini aç" }).click();
  const image = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64");
  await page.getByLabel("Fotoğraf ve video seç").setInputFiles({ name: "antrenman.jpg", mimeType: "image/png", buffer: image });
  await expect(page.locator(".conflict-preview img")).toBeVisible();
  await expect(page.locator(".conflict-preview img")).toHaveJSProperty("complete", true);
  await page.getByRole("button", { name: "Kararı uygula" }).click();
  await expect(page.getByRole("heading", { name: "antrenman.jpg", exact: true })).toHaveCount(2);
  await page.getByRole("button", { name: "Kaydedilmiş montajı render et" }).click();
  await expect(page.getByLabel("Kaydedilmiş Reel önizlemesi", { exact: true })).toBeVisible();
  await verify();
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Kaldır", exact: true }).click();
  await expect(page).toHaveURL(/#\/welcome$/); await verify();
  await page.getByRole("link", { name: "Demo", exact: true }).click();
  await ready(page);
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await expect(page.getByRole("button", { name: "Kaldır", exact: true })).toBeEnabled(); await verify();
});

test("review approval updates local completed history without publishing", async ({ page }) => {
  const verify = await watchIsolation(page);
  await page.goto("/#/demo/dashboard"); await ready(page);
  await page.getByRole("link", { name: "İnceleme özeti", exact: true }).click();
  await page.getByRole("button", { name: "Onayla ve yayınla", exact: true }).click();
  await page.getByRole("button", { name: "Yayınlamayı onayla", exact: true }).click();
  await expect(page.getByText("Yayınlama onayı alındı.", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Tamamlanmış paketler", exact: true }).click();
  await expect(page.getByLabel("Tamamlanmış paket seç").locator("option")).toHaveCount(3);
  await verify();
});

test("real pairing marker redirects before validation and retains query", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("aisomedo:real-paired:v1", "1"));
  const calls: string[] = [];
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    calls.push(new URL(page.url()).hash); await route.fulfill({ status: 401, json: {} });
  });
  await page.goto("/#/demo/package?review=7&folder=a%20b");
  await expect(page).toHaveURL(/#\/package\?review=7&folder=a%20b$/);
  await expect(page.getByRole("heading", { name: "Tarayıcıyı eşleştir" })).toBeVisible();
  expect(calls.length).toBeGreaterThan(0); expect(calls.every(hash => hash === "#/package?review=7&folder=a%20b")).toBe(true);
});
