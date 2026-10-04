import { test, expect, type Page } from "@playwright/test";
import { client, dashboard, emptyEditor, setupState } from "../src/test/fixtures";

async function fixture(page: Page) {
  const state = {
    plan: dashboard().plan,
    branding: { logo_asset: null, caption_template: "Dojo", intro_asset: null, intro_duration: null, outro_asset: null, outro_duration: null },
    reminders: { interval_minutes: 360, delivery_start: "08:00:00", delivery_end: "22:00:00", timezone: "Europe/Istanbul" },
    instagram: { health: "reconnect_required", ig_username: "old_dojo" },
    reminderStatus: 200, errors: [] as string[],
  };
  page.on("pageerror", error => state.errors.push(error.message));
  await page.addInitScript(() => { window.open = () => null; });
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const path = new URL(route.request().url()).pathname, method = route.request().method();
    const json = (value: unknown, status = 200) => route.fulfill({ status, json: value });
    if (path === "/api/compat") return json({ api_version: "0.1.0" });
    if (path === "/api/pairing/me") return json(client);
    if (path === "/api/setup") return json(setupState());
    if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (path === "/api/dashboard") return json({ ...dashboard(), plan: state.plan });
    if (path === "/api/packages/active/editor") return json(emptyEditor());
    if (path === "/api/settings/plan") {
      if (method === "PUT") state.plan = { ...state.plan, ...route.request().postDataJSON() };
      return json(state.plan);
    }
    if (path === "/api/settings/branding") {
      if (method === "PATCH") state.branding = { ...state.branding, ...route.request().postDataJSON() };
      return json(state.branding);
    }
    if (path === "/api/settings/reminders") {
      if (method === "PUT" && state.reminderStatus === 200) state.reminders = route.request().postDataJSON();
      return json(state.reminders, method === "PUT" ? state.reminderStatus : 200);
    }
    if (path === "/api/meta/status") return json(state.instagram);
    if (path === "/api/meta/oauth/start") return json({ auth_url: "https://www.facebook.com/dialog/oauth", attempt_id: "a1" });
    if (path === "/api/meta/oauth/attempts/a1") return json({ id: "a1", status: "completed", candidates: [{ ig_user_id: "2", ig_username: "new_dojo" }] });
    if (path === "/api/meta/oauth/attempts/a1/select") { state.instagram = { health: "healthy", ig_username: "new_dojo" }; return json(state.instagram); }
    if (path === "/api/setup/consent") return json({ version: 2, text: "Öğrenci medyasını yayınlamadan önce gerekli izinleri alın.", accepted_at: "2026-08-03T07:00:00Z" });
    if (path === "/api/activity") return json({ events: [{ id: 7, action: "reminders.policy_updated", actor: client, details: {}, occurred_at: "2026-08-03T07:00:00Z" }], next_cursor: null });
    state.errors.push(`Unexpected API request: ${method} ${path}`); return json({}, 404);
  });
  await page.goto("/#/settings");
  await expect(page.getByLabel("Yayın saati")).toHaveValue("10:00");
  return state;
}

test("settings persist and remain keyboard-accessible; consent and recent activity are visible", async ({ page }, info) => {
  const state = await fixture(page);
  await page.getByLabel("Yayın saati").fill("13:30");
  await page.getByRole("button", { name: "Planı kaydet" }).click();
  await expect(page.getByRole("region", { name: "Dojo Yayın Planı" }).getByRole("status").filter({ hasText: "Ayarlar kaydedildi." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dojo Yayın Planı" })).toBeFocused();
  await page.getByRole("textbox", { name: "Açıklama şablonu" }).fill("Yeni Dojo {title}");
  await page.getByRole("button", { name: "Açıklamayı kaydet" }).click();
  await expect(page.getByRole("region", { name: "Açıklama şablonu" }).getByRole("status").filter({ hasText: "Ayarlar kaydedildi." })).toBeVisible();
  await page.getByLabel("Hatırlatma aralığı (dakika)").fill("120");
  await page.getByLabel("Bildirim başlangıcı").fill("22:00");
  await page.getByLabel("Bildirim bitişi").fill("08:00");
  const save = page.getByRole("button", { name: "Hatırlatmaları kaydet" });
  await save.focus(); await save.press("Enter");
  await expect(page.getByRole("region", { name: "Hatırlatmalar" }).getByRole("status").filter({ hasText: "Ayarlar kaydedildi." })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Yayın saati")).toHaveValue("13:30");
  await expect(page.getByRole("textbox", { name: "Açıklama şablonu" })).toHaveValue("Yeni Dojo {title}");
  await expect(page.getByLabel("Hatırlatma aralığı (dakika)")).toHaveValue("120");
  await expect(page.getByLabel("Bildirim başlangıcı")).toHaveValue("22:00");
  await expect(page.getByText(/Rıza kaydedildi/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.CAPTURE_UI) await page.screenshot({ path: info.outputPath("settings.png"), fullPage: true });
  await page.getByRole("link", { name: "Etkinlik", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Hatırlatma ayarları güncellendi" })).toBeVisible();
  await expect(page.getByRole("list").getByText(client.name)).toBeVisible();
  await expect(page.locator("time")).toHaveAttribute("datetime", "2026-08-03T07:00:00Z");
  expect(state.errors).toEqual([]);
});

test("failed reminder save preserves draft; OAuth reconnect preserves package and plan", async ({ page }) => {
  const state = await fixture(page);
  state.reminderStatus = 500;
  await page.getByLabel("Hatırlatma aralığı (dakika)").fill("60");
  await page.getByRole("button", { name: "Hatırlatmaları kaydet" }).click();
  const region = page.getByRole("region", { name: "Hatırlatmalar" });
  await expect(region.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Hatırlatma aralığı (dakika)")).toHaveValue("60");
  state.reminders.interval_minutes = 90;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(region.getByRole("button", { name: "Sunucudaki değerleri yükle" })).toBeVisible();
  await expect(page.getByLabel("Hatırlatma aralığı (dakika)")).toHaveValue("60");
  await region.getByRole("button", { name: "Sunucudaki değerleri yükle" }).click();
  await expect(page.getByLabel("Hatırlatma aralığı (dakika)")).toHaveValue("90");
  await expect(page.getByText(/@old_dojo.*Yeniden bağlantı/)).toBeVisible();
  await page.getByRole("button", { name: "Instagram ile yetkilendir" }).click();
  await expect(page.getByRole("link", { name: "Yetkilendirme sayfasını aç" })).toHaveAttribute("href", "https://www.facebook.com/dialog/oauth");
  await page.getByRole("button", { name: "@new_dojo hesabını seç" }).click();
  await expect(page.getByText(/@new_dojo.*Bağlantı doğrulandı/)).toBeVisible();
  await page.getByRole("link", { name: "Kontrol Paneli", exact: true }).click();
  await expect(page.getByText("03-08-2026 10-00")).toBeVisible();
  expect(state.plan.anchor_date).toBe("2026-08-03");
  expect(state.errors).toEqual([]);
});
