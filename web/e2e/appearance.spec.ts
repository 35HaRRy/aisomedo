import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { client, dashboard, emptyEditor, setupState } from "../src/test/fixtures";
import { installLiveStream } from "./live-fixture";

const video = readFileSync(fileURLToPath(new URL("./fixtures/timeline.mp4", import.meta.url)));

async function fixture(page: Page) {
  await installLiveStream(page);
  const data = dashboard();
  data.package = { id: 1, folder_name: "2026-11-02-dojo", status: "preparing", created_at: "2026-10-26T09:00:00Z" };
  data.next_slot = { kind: "regular", due_at: "2026-11-02T15:00:00Z" };
  data.instagram.username = "aikido_istanbul_dojo";
  data.pending_actions = [{ occurrence_id: 1, review_id: 2, version: 1, state: "review_ready", package_folder: data.package.folder_name, due_at: data.next_slot.due_at }];
  const editor = { ...emptyEditor(), package: data.package, render_stale: false, render_status: "ready", render_duration: 25, render_preview_url: "/api/appearance-preview" };
  const errors: string[] = [];
  let paired = true;
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (path === "/api/appearance-preview") return route.fulfill({ contentType: "video/mp4", body: video });
    if (path === "/api/compat") return json({ api_version: "0.1.0" });
    if (path === "/api/pairing/me") return json({ ...client, name: "Dojo Web Yöneticisi" }, paired ? 200 : 401);
    if (path === "/api/setup") return json(setupState());
    if (path === "/api/dashboard") return json(data);
    if (path === "/api/packages/active/editor") return json(editor);
    if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 10 * 2 ** 30 });
    if (path === "/api/settings/reminders") return json({ interval_minutes: 360, delivery_start: "08:00:00", delivery_end: "22:00:00", timezone: "Europe/Istanbul" });
    if (path === "/api/meta/status") return json({ health: "healthy", ig_username: data.instagram.username });
    if (path === "/api/settings/plan") return json(data.plan);
    if (path === "/api/settings/branding") return json({ logo_asset: null, caption_template: "Dojo {title}", intro_asset: null, intro_duration: null, outro_asset: null, outro_duration: null });
    if (path === "/api/setup/consent") return json({ version: 1, text: "Öğrenci medyasını yayınlamadan önce gerekli izinleri alın.", accepted_at: data.generated_at });
    if (path === "/api/activity") return json({ events: ["2026-10-28T08:00:00Z", "2026-10-28T07:45:00Z", "2026-10-27T14:30:00Z", "2026-10-25T10:00:00Z"].map((date, i) => ({ id: i + 1, action: "future.event", actor: { ...client, name: ["Dojo Otomasyonu", "Dojo Video İşleyici", "Dojo Web Yöneticisi", "Dojo Web Yöneticisi"][i] }, details: {}, occurred_at: date })), next_cursor: null });
    if (path === "/api/packages") return json([{ ...data.package, id: 3, folder_name: "2026-10-19-dojo", status: "completed" }]);
    if (path === "/api/packages/2026-10-19-dojo") return json({ folder_name: "2026-10-19-dojo", caption: "Dojo antrenmanı\n#dojo #aikido", media: [], order: [], render_revision: "saved", artifacts: [{ artifact_ref: "render/reel.mp4", kind: "render", filename: "reel.mp4", content_type: "video/mp4", available: true, url: "/api/appearance-preview", preview_url: "/api/appearance-preview" }] });
    if (path === "/api/reviews/2") return json({ review: { id: 2, occurrence_id: 1, version: 1, package_folder: data.package!.folder_name, revision_digest: "saved", caption: "Dojo antrenmanı\n#dojo #aikido", status: "pending", created_at: data.generated_at }, render_ready: true, preview_url: "/api/appearance-preview", next_regular_at: "2026-11-16T15:00:00Z" });
    errors.push(`Unexpected request: ${path}`);
    return json({}, 404);
  });
  return { errors, unpair: () => { paired = false; } };
}

for (const theme of ["light", "dark"] as const) {
  test(`${theme} appearance preserves navigation, readable surfaces and responsive layouts`, async ({ page }, info) => {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    const server = await fixture(page);
    const routes = [
      ["dashboard", "Kontrol Paneli"], ["package", "Güncel Paket"], ["activity", "Etkinlik"],
      ["settings", "Ayarlar"], ["completed", "Tamamlanmış paketler"],
      ["package?review=2", "Yayın İncelemesi"], ["onboarding", "Kurulum tamamlandı"],
    ];
    for (const [route, heading] of routes) {
      await page.goto(`/#/${route}`);
      await expect(page.getByRole("heading", { name: heading, exact: true, level: 1 })).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("navigation").getByRole("link")).toHaveCount(5);
      if (route === "package") {
        // Preserve the existing collapsed default; expand only for screenshot comparison.
        await expect(page.getByRole("button", { name: "Fotoğraf ve video yükle panelini aç" })).toHaveAttribute("aria-expanded", "false");
        await page.getByRole("button", { name: "Fotoğraf ve video yükle panelini aç" }).click();
        await expect(page.getByLabel("Fotoğraf ve video seç")).toBeVisible();
      }
      if (route === "completed") await expect(page.getByRole("heading", { name: "2026-10-19-dojo" })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await expect.poll(() => page.locator("video").evaluateAll(videos => videos.every(video => video.readyState >= 2))).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      if (process.env.CAPTURE_UI) await page.screenshot({ path: `../.impeccable/review/${info.project.name}-${theme}-${route.replace("?review=2", "-review")}.png`, fullPage: true });
    }
    server.unpair();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Tarayıcıyı eşleştir" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (process.env.CAPTURE_UI) await page.screenshot({ path: `../.impeccable/review/${info.project.name}-${theme}-pairing.png`, fullPage: true });
    expect(server.errors).toEqual([]);
  });
}

test("appearance switch survives navigation and reload, overriding system appearance", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await fixture(page);
  await page.goto("/#/dashboard");
  await page.getByRole("button", { name: "Açık Mod" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("link", { name: "Etkinlik", exact: true }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Koyu Mod" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
