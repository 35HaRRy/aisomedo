import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { client, dashboard, emptyEditor, setupState } from "../src/test/fixtures";
import { installLiveStream, invalidateLive } from "./live-fixture";

const bytes = readFileSync(fileURLToPath(new URL("./fixtures/timeline.mp4", import.meta.url)));
async function fixture(page: Page, continuation = false) {
  await installLiveStream(page);
  const state = dashboard(), writes: { path: string; body: unknown }[] = [], errors: string[] = [];
  let status = 200;
  let publication: { status: string; error: string | null } | null = null;
  const review = { id: 2, occurrence_id: 1, version: 3, package_folder: state.package!.folder_name,
    revision_digest: "immutable-revision", caption: "Dojo antrenmanı\n#dojo #birlikte", status: "pending", created_at: state.generated_at };
  state.pending_actions = [{ occurrence_id: 1, review_id: 2, version: 3, package_folder: review.package_folder, state: "review_ready", due_at: state.generated_at }];
  const preview = `/api/packages/active/render/preview?expected_folder_name=${encodeURIComponent(review.package_folder)}&revision=immutable-revision`;
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = (value: unknown, code = 200) => route.fulfill({ status: code, json: value });
    if (path.endsWith("/preview")) {
      expect(url.searchParams.get("revision")).toBe("immutable-revision");
      expect(url.searchParams.get("expected_folder_name")).toBe(review.package_folder);
      const range = route.request().headers()["range"]?.match(/^bytes=(\d+)-(\d*)$/);
      const start = range ? Number(range[1]) : 0, end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
      return route.fulfill({ status: range ? 206 : 200, body: bytes.subarray(start, end + 1), headers: {
        "Content-Type": "video/mp4", "Accept-Ranges": "bytes", "Cache-Control": "private, no-store",
        ...(range ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` } : {}),
      } });
    }
    if (path === "/api/compat") return json({ api_version: "0.1.0" });
    if (path === "/api/pairing/me") return json(client);
    if (path === "/api/setup") return json(setupState());
    if (path === "/api/dashboard") return json(state);
    if (path === "/api/packages/active/editor") return json(emptyEditor());
    if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (path === "/api/reviews/2") {
      const ready = ["pending", "failed", "uncertain"].includes(review.status);
      return json({ review, render_ready: ready, preview_url: ready ? preview : null, next_regular_at: "2026-08-17T07:00:00Z" });
    }
    if (path.startsWith("/api/reviews/2/") && route.request().method() === "POST") {
      writes.push({ path, body: route.request().postDataJSON() });
      const unconfirmed = path.endsWith("/approve") && publication && ["failed", "uncertain", "publishing"].includes(publication.status);
      review.status = status === 409 ? "skipped" : unconfirmed ? publication!.status : path.endsWith("/approve") ? "approved" : path.endsWith("/skip") ? "skipped" : "rescheduled";
      if (!unconfirmed) state.pending_actions = [];
      return json({ review, publication, next_regular_at: "2026-08-17T07:00:00Z" }, status);
    }
    errors.push(`Unexpected API request ${path}`); return json({}, 404);
  });
  if (continuation) await page.goto(`/#/package?occurrence=1&folder=${encodeURIComponent(review.package_folder)}`);
  else {
    await page.goto("/#/dashboard");
    await page.getByRole("link", { name: "İnceleme özeti" }).click();
  }
  await expect(page.getByRole("heading", { name: "Yayın İncelemesi", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Onayla ve yayınla" })).toBeEnabled();
  return { state, writes, errors, preview, setStatus: (value: number) => { status = value; },
    setPublication: (value: typeof publication) => { publication = value; } };
}

test("review header icons stay top-right and panels toggle without decisions", async ({ page }, info) => {
  const server = await fixture(page);
  const panel = page.getByRole("region", { name: server.state.package!.folder_name, exact: true });
  for (const control of [panel.getByRole("button", { name: "İncelemeyi yenile" }), panel.getByRole("link", { name: "Paketi düzenle" })]) {
    await expect(control).toHaveText("");
    await expect(control.locator("svg")).toBeVisible();
    const box = (await control.boundingBox())!, heading = (await panel.getByRole("heading", { level: 2 }).boundingBox())!;
    expect(Math.abs(box.y - heading.y)).toBeLessThan(50);
  }
  for (const name of ["Onayla ve yayınla", "Bu zamanı atla", "Başka zamana planla"])
    await expect(panel.getByRole("button", { name }).locator("svg")).toBeVisible();
  await page.screenshot({ path: info.outputPath("review-icons.png"), fullPage: true });
  await panel.getByRole("button", { name: /panelini kapat$/ }).click();
  await expect(page.getByRole("button", { name: "Onayla ve yayınla" })).toBeHidden();
  await panel.getByRole("button", { name: /panelini aç$/ }).click();
  await expect(page.getByRole("button", { name: "Onayla ve yayınla" })).toBeEnabled();
  expect(server.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(server.errors).toEqual([]);
});

test("collapsing review pauses playback and preserves pending confirmation", async ({ page }) => {
  const server = await fixture(page);
  const video = page.getByLabel("İncelenen Reel");
  await video.evaluate((media: HTMLVideoElement) => media.play());
  await expect.poll(() => video.evaluate((media: HTMLVideoElement) => media.paused)).toBe(false);
  await page.getByRole("button", { name: "Onayla ve yayınla" }).click();
  await page.getByRole("button", { name: /panelini kapat$/ }).click();
  await expect(video).toBeHidden();
  await expect.poll(() => video.evaluate((media: HTMLVideoElement) => media.paused)).toBe(true);
  await page.getByRole("button", { name: /panelini aç$/ }).click();
  await expect(page.getByRole("button", { name: "Yayınlamayı onayla" })).toBeVisible();
  expect(server.writes).toEqual([]);
});

test("future oneoff review waits for its worker review and opens approval without publishing", async ({ page }, info) => {
  const server = await fixture(page);
  const slot = { occurrence_id: 1, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  const folder = server.state.package!.folder_name;
  server.state.pending_actions = [];
  server.state.next_slots = [slot];
  await page.route("**/api/dashboard/occurrences/1/decision", async route => {
    const body = route.request().postDataJSON();
    expect(body).toEqual({ expected_due_at: slot.due_at, action: "review", confirmed: false });
    server.writes.push({ path: new URL(route.request().url()).pathname, body });
    slot.due_at = server.state.generated_at;
    server.state.pending_actions = [{ occurrence_id: 1, review_id: null, version: null, due_at: slot.due_at, package_folder: folder, state: "preparing" }];
    await route.fulfill({ json: { occurrence_id: 1, due_at: slot.due_at, status: "pending", package_folder: folder } });
  });
  await page.goto("/#/dashboard"); await page.reload();
  await page.getByRole("button", { name: "İncele ve yayınla" }).click();
  await expect(page.getByRole("status")).toContainText("Reel hazırlanıyor");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("oneoff-worker-wait.png"), fullPage: true });
  server.state.pending_actions = [{ occurrence_id: 9, review_id: 99, version: 1, due_at: slot.due_at, package_folder: folder, state: "review_ready" }];
  await invalidateLive(page);
  await expect(page.getByRole("heading", { name: "Kontrol Paneli", exact: true })).toBeVisible();
  server.state.pending_actions = [{ occurrence_id: 1, review_id: 2, version: 3, due_at: slot.due_at, package_folder: folder, state: "review_ready" }];
  await invalidateLive(page);
  await expect(page.getByRole("button", { name: "Onayla ve yayınla" })).toBeEnabled();
  expect(server.writes).toHaveLength(1);
  expect(server.errors).toEqual([]);
});

test("future oneoff skip requires confirmation and removes the scheduled slot", async ({ page }, info) => {
  const server = await fixture(page);
  const slot = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  server.state.pending_actions = []; server.state.next_slots = [slot];
  await page.route("**/api/dashboard/occurrences/8/decision", async route => {
    const body = route.request().postDataJSON();
    expect(body).toEqual({ expected_due_at: slot.due_at, action: "skip", confirmed: true });
    server.writes.push({ path: new URL(route.request().url()).pathname, body });
    server.state.next_slots = [];
    await route.fulfill({ json: { occurrence_id: 8, due_at: slot.due_at, status: "skipped", package_folder: server.state.package!.folder_name } });
  });
  await page.goto("/#/dashboard"); await page.reload();
  await page.getByRole("button", { name: "Bu zamanı atla" }).click();
  expect(server.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("oneoff-skip-confirmation.png"), fullPage: true });
  await page.getByRole("button", { name: "Atlamayı onayla" }).click();
  await expect(page.getByText("Bu Yayın Zamanı atlandı. Paket korunuyor.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Sonraki Yayın Zamanı" })).toHaveCount(0);
  expect(server.writes).toHaveLength(1);
  expect(server.errors).toEqual([]);
});

test("dashboard changes future oneoff date before next regular", async ({ page }, info) => {
  const server = await fixture(page);
  const oneoff = { occurrence_id: 8, kind: "oneoff", due_at: "2099-08-04T07:00:00Z" };
  server.state.pending_actions = [];
  server.state.next_slots = [oneoff, { kind: "regular", due_at: "2099-08-17T07:00:00Z" }];
  await page.route("**/api/dashboard/occurrences/8", async route => {
    expect(route.request().method()).toBe("PATCH");
    const body = route.request().postDataJSON();
    expect(body).toEqual({ expected_due_at: "2099-08-04T07:00:00Z", new_due_at: "2099-08-05T12:30:00+03:00" });
    oneoff.due_at = body.new_due_at;
    server.state.generated_at = "2026-10-23T12:00:01Z";
    await route.fulfill({ json: oneoff });
  });
  await page.goto("/#/dashboard");
  await page.reload();
  await page.getByRole("button", { name: "Tarihi değiştir" }).click();
  const input = page.getByLabel("Yeni yayın tarihi ve saati");
  await input.fill("2099-08-17T10:00");
  await expect(page.getByRole("button", { name: "Kaydet", exact: true })).toBeDisabled();
  await input.fill("2099-08-05T12:30");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("oneoff-date-editor.png"), fullPage: true });
  await page.getByRole("button", { name: "Kaydet", exact: true }).click();
  await expect(page.getByRole("list", { name: "Sonraki Yayın Zamanı" })).toContainText("5 Ağustos 2099 12:30");
  expect(server.errors).toEqual([]);
});

test("dashboard lists pending oneoff and regular times together", async ({ page }, info) => {
  const server = await fixture(page);
  const oneoff = { kind: "oneoff", due_at: "2026-08-04T07:00:00Z" };
  server.state.next_slots = [oneoff, { kind: "regular", due_at: "2026-08-17T07:00:00Z" }];
  server.state.next_slot = oneoff;
  await page.goto("/#/dashboard");
  await page.reload();
  const list = page.getByRole("list", { name: "Sonraki Yayın Zamanı" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list).toContainText("Yeniden planlanan yayın");
  await expect(list).toContainText("Düzenli yayın");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("pending-publication-times.png"), fullPage: true });
  expect(server.writes).toEqual([]);
});

test("exact playable review, responsive confirmation and explicit publication", async ({ page }, info) => {
  const server = await fixture(page);
  const video = page.getByLabel("İncelenen Reel");
  await expect(video).toHaveAttribute("src", server.preview);
  await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.duration)).toBe(30);
  await expect(page.getByText("Dojo antrenmanı\n#dojo #birlikte")).toBeVisible();
  await expect(page.getByLabel("Fotoğraf ve video seç")).toHaveCount(0);
  expect(server.writes).toEqual([]);
  await page.getByRole("button", { name: "Onayla ve yayınla" }).click();
  await expect(page.getByText(/Instagram.*hemen/)).toBeVisible();
  expect(server.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Vazgeç", exact: true }).focus();
  await expect(page.getByRole("button", { name: "Vazgeç", exact: true })).toBeFocused();
  await page.screenshot({ path: info.outputPath("review-confirmation.png"), fullPage: true });
  await page.getByRole("button", { name: "Vazgeç", exact: true }).click();
  expect(server.writes).toEqual([]);
  await page.getByRole("button", { name: "Onayla ve yayınla" }).click();
  await page.getByRole("button", { name: "Yayınlamayı onayla", exact: true }).click();
  await expect(page.getByText("Yayınlama onayı alındı.")).toBeVisible();
  expect(server.writes).toEqual([{ path: "/api/reviews/2/approve", body: { version: 3 } }]);
  expect(server.errors).toEqual([]);
});

test("Istanbul reschedule and other-device conflict cannot replay action", async ({ page }, info) => {
  await page.addInitScript(() => { Date.now = () => new Date("2026-08-03T07:00:00Z").getTime(); });
  const server = await fixture(page);
  await page.getByRole("button", { name: "Başka zamana planla" }).click();
  await page.getByLabel("Yeni Yayın Zamanı (İstanbul)").fill("2000-08-04T12:30");
  await expect(page.getByRole("button", { name: "Yeni zamanı onayla", exact: true })).toBeDisabled();
  for (const invalid of ["2026-08-17T10:00", "2026-08-18T10:00"]) {
    await page.getByLabel("Yeni Yayın Zamanı (İstanbul)").fill(invalid);
    await expect(page.getByRole("button", { name: "Yeni zamanı onayla", exact: true })).toBeDisabled();
  }
  await page.getByLabel("Yeni Yayın Zamanı (İstanbul)").fill("2026-08-04T12:30");
  await page.screenshot({ path: info.outputPath("reschedule-bounds.png"), fullPage: true });
  server.setStatus(409);
  await page.getByRole("button", { name: "Yeni zamanı onayla", exact: true }).click();
  await expect(page.getByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Onayla ve yayınla" })).toHaveCount(0);
  expect(server.writes).toEqual([{ path: "/api/reviews/2/reschedule", body: { version: 3, new_due_at: "2026-08-04T12:30:00+03:00" } }]);
  expect(server.errors).toEqual([]);
});

for (const continuation of [false, true]) test(`failed publication stays visible without resending (${continuation ? "continuation" : "direct review"})`, async ({ page }, info) => {
  const server = await fixture(page, continuation);
  server.setPublication({ status: "failed", error: "Instagram publishing requires a publicly reachable HTTPS video URL; configure PUBLIC_HTTPS_ORIGIN or PUBLIC_BASE_URL (localhost/private addresses are not supported)" });
  await page.getByRole("button", { name: "Onayla ve yayınla" }).click();
  await page.getByRole("button", { name: "Yayınlamayı onayla", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Instagram'a yayın yapılamadı");
  await expect(page.getByRole("alert")).toContainText("PUBLIC_BASE_URL");
  await expect(page.getByText("Yayınlama onayı alındı.", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "İncelemeyi yenile" }).click();
  await expect(page.getByRole("alert")).toContainText("Video korunuyor");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("publication-failed.png"), fullPage: true });
  expect(server.writes).toEqual([{ path: "/api/reviews/2/approve", body: { version: 3 } }]);
  expect(server.errors).toEqual([]);
});
