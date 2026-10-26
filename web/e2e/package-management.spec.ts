import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { packageSnapshot } from "../src/packages/testFixtures";
import { client, dashboard, setupState } from "../src/test/fixtures";
import { installLiveStream, invalidateLive } from "./live-fixture";

const bytes = readFileSync(fileURLToPath(new URL("./fixtures/timeline.mp4", import.meta.url)));
const card = (page: Page, filename: string) => page.getByRole("list", { name: "Montaj sırası" }).locator(":scope > li").filter({ has: page.getByRole("heading", { name: filename, exact: true }) });
async function fixture(page: Page, photo = false) {
  await installLiveStream(page);
  const snapshot = packageSnapshot(); const writes: unknown[] = [], errors: string[] = [];
  let cleared = false;
  if (photo) {
    snapshot.media.push({ ...snapshot.media[0], media_id: "photo", filename: "photo.jpg", is_video: false, source_duration: null, effective_duration: 3, preview_url: null, preview_ref: null, artifacts: [] });
    snapshot.montage.order.push("photo");
    snapshot.montage.combined_duration = 63;
  }
  const archived = "Çalışma-completed", original = `/api/packages/${encodeURIComponent(archived)}/artifacts?artifact_ref=media%2Fa%2Foriginal.MP4&download=true`;
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()), path = decodeURIComponent(url.pathname), method = route.request().method();
    const json = (value: unknown, status = 200) => route.fulfill({ status, json: value });
    if (path.endsWith("/thumbnail")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="120"><rect width="180" height="120" fill="#16665b"/></svg>' });
    if (path.endsWith("/preview") || path.endsWith("/artifacts") || path.endsWith("/original")) {
      const range = route.request().headers()["range"]?.match(/^bytes=(\d+)-(\d*)$/);
      const start = range ? Number(range[1]) : 0, end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
      await route.fulfill({ status: range ? 206 : 200, body: bytes.subarray(start, end + 1),
        headers: { "Content-Type": "video/mp4", "Accept-Ranges": "bytes", "Cache-Control": "private, no-store",
          ...(range ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` } : {}),
          ...(url.searchParams.get("download") === "true" ? { "Content-Disposition": "attachment; filename*=utf-8''%C3%87al%C4%B1%C5%9Fma.MP4" } : {}) } }); return;
    }
    if (path === "/api/compat") return json({ api_version: "0.1.0" });
    if (path === "/api/pairing/me") return json(client);
    if (path === "/api/setup") return json(setupState());
    if (path === "/api/dashboard") return json({ ...dashboard(), package: cleared ? null : snapshot.package });
    if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (path === "/api/packages/active/editor") return json(cleared ? {} : snapshot, cleared ? 404 : 200);
    if (path === "/api/packages") return json([{ ...snapshot.package, id: 9, folder_name: archived, status: "completed" }]);
    if (path === `/api/packages/${archived}`) return json({ folder_name: archived, media: [{ ...snapshot.media[0], filename: "Çalışma.MP4", preview_url: null, artifacts: [{ artifact_ref: "media/a/original.MP4", kind: "original", filename: "Çalışma.MP4", content_type: "video/mp4", available: true, url: original, preview_url: null }] }], order: ["a"], caption: null, render_revision: null, artifacts: [{ artifact_ref: "render/reel.mp4", kind: "render", filename: "reel.mp4", content_type: "video/mp4", available: false, url: null, preview_url: null }] });
    if (method !== "GET" && path.startsWith("/api/packages/active/")) {
      const body = route.request().postDataJSON(); writes.push({ path, body });
      if (path.endsWith("/clear")) { cleared = true; return json({ folder_name: snapshot.package.folder_name, upload_ids: [] }); }
      if (path.endsWith("/render")) {
        snapshot.render_status = "ready"; snapshot.render_stale = false; snapshot.render_revision = "saved";
        snapshot.render_preview_url = "/api/packages/active/render/preview?revision=saved";
        return json({ stale: true, render_revision: "saved" });
      }
      if (path.endsWith("/edits")) {
        if (body.base_content_revision > snapshot.content_revision) return json({}, 409);
        for (const change of body.changes) {
          const id = change.key.slice(change.key.indexOf(":") + 1);
          const current = change.key.startsWith("video:") ? { ranges: snapshot.montage.selections[id] ?? [] }
            : { seconds: snapshot.media.find(m => m.media_id === id)!.effective_duration };
          if (JSON.stringify(current) !== JSON.stringify(change.base) && JSON.stringify(current) !== JSON.stringify(change.proposed)) return json({}, 409);
        }
        // Grouped edits return the authoritative editor snapshot.
        for (const change of body.changes) {
          const id = change.key.slice(change.key.indexOf(":") + 1);
          if (change.key.startsWith("video:")) {
            snapshot.montage.selections[id] = change.proposed.ranges;
            snapshot.media.find(m => m.media_id === id)!.section_preview = change.proposed.ranges.length
              ? { status: "queued", generation: `saved-${snapshot.content_revision}`, url: null, duration: null }
              : { status: "missing", generation: null, url: null, duration: null };
          }
          else if (change.key.startsWith("photo:")) {
            const media = snapshot.media.find(m => m.media_id === id);
            if (media) media.effective_duration = change.proposed.seconds;
          }
        }
        snapshot.content_revision += 1;
      }
      else if (path.endsWith("/selections")) snapshot.montage.selections = body.selections;
      else if (path.endsWith("/order")) snapshot.montage.order = body.order;
      else {
        const media = snapshot.media.find(m => path.includes(`/media/${m.media_id}/`));
        if (!media) { errors.push(`unexpected mutation ${path}`); return json({}, 404); }
        if (path.endsWith("/remove")) { media.status = "removed"; media.removed_position = snapshot.montage.order.indexOf(media.media_id); snapshot.montage.order = snapshot.montage.order.filter(id => id !== media.media_id); }
        else if (path.endsWith("/restore")) { media.status = "finalized"; snapshot.montage.order.splice(media.removed_position ?? 0, 0, media.media_id); }
        else errors.push(`unexpected mutation ${path}`);
      }
      for (const media of snapshot.media) media.effective_duration = media.is_video
        ? snapshot.montage.selections[media.media_id]?.reduce((sum, r) => sum + r.end - r.start, 0) ?? 30
        : body.photo_durations?.[media.media_id] ?? media.effective_duration;
      snapshot.montage.combined_duration = snapshot.media.filter(m => m.status === "finalized").reduce((sum, m) => sum + (m.effective_duration ?? 0), 0);
      snapshot.render_stale = true; snapshot.render_status = "stale"; snapshot.render_preview_url = null;
      return json(path.endsWith("/edits") ? snapshot : snapshot.montage);
    }
    errors.push(`unexpected API call ${method} ${path}`); return json({}, 404);
  });
  await page.goto("/#/package");
  try { await expect(page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" })).toBeVisible(); }
  catch (failure) { throw new Error(`Fixture/page errors: ${JSON.stringify(errors)}; ${failure}`); }
  return { snapshot, writes, errors, original };
}

async function gesture(page: Page, target: Locator, start: { x: number; y: number }, end: { x: number; y: number }, mobile: boolean, cancel = false) {
  if (mobile) {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ ...start, id: 1 }] });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ ...end, id: 1 }] });
    await cdp.send("Input.dispatchTouchEvent", { type: cancel ? "touchCancel" : "touchEnd", touchPoints: [] });
    await cdp.detach();
  } else {
    await page.mouse.move(start.x, start.y); await page.mouse.down(); await page.mouse.move(end.x, end.y, { steps: 8 });
    if (cancel) await target.dispatchEvent("pointercancel", { pointerId: 1 });
    await page.mouse.up();
  }
}

test("package panels toggle independently and completed navigation protects drafts", async ({ page }, info) => {
  const server = await fixture(page);
  await expect(page.getByRole("heading", { name: "Bekleyen işlem" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Tamamlanmış paketler", exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("package-panels.png"), fullPage: true });
  const panel = page.getByRole("region", { name: "Aktif paket medyası", exact: true });
  const toggle = panel.getByRole("button", { name: "Aktif paket medyası panelini kapat", exact: true });
  const heading = await panel.getByRole("heading", { name: "Aktif paket medyası", exact: true }).boundingBox();
  const bounds = await toggle.boundingBox();
  expect(Math.abs(bounds!.y - heading!.y)).toBeLessThan(50);
  expect(heading!.width).toBeGreaterThan(120);
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await page.getByRole("button", { name: "Bölüm ekle", exact: true }).click();
  await page.getByLabel("1. bölüm bitişi (saniye)").fill("5");
  await toggle.click();
   await expect(panel.getByRole("button", { name: "Bölümleri kaydet" }).first()).toBeHidden();
  await expect(page.getByLabel("Fotoğraf ve video seç")).toBeVisible();
  await panel.getByRole("button", { name: "Aktif paket medyası panelini aç", exact: true }).click();
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("5");
  await page.getByRole("link", { name: "Tamamlanmış paketler", exact: true }).click();
  await page.getByRole("button", { name: "Vazgeç", exact: true }).click();
  await expect(page).toHaveURL(/#\/package$/);
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("5");
  await page.getByRole("link", { name: "Tamamlanmış paketler", exact: true }).click();
  await page.getByRole("button", { name: "Değişiklikleri at", exact: true }).click();
  await expect(page).toHaveURL(/#\/completed$/);
  await expect(page.getByRole("heading", { level: 1, name: "Tamamlanmış paketler" })).toBeVisible();
  expect(server.writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Tamamlanmış paketler" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("completed-page.png"), fullPage: true });
  expect(server.errors).toEqual([]);
});

test("timeline geometry, native seek, drafts, persistence and cancellation", async ({ page, isMobile }, info) => {
  const server = await fixture(page);
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  const track = page.getByRole("group", { name: "Video zaman çizelgesi" });
  for (const [start, end] of [[0, 5], [10, 15], [24, 30]]) {
    await track.scrollIntoViewIfNeeded(); const box = (await track.boundingBox())!;
    await gesture(page, track, { x: box.x + Math.max(1, start / 30 * box.width), y: box.y + box.height / 2 }, { x: box.x + Math.min(box.width - 1, end / 30 * box.width), y: box.y + box.height / 2 }, !!isMobile);
  }
  await expect(page.getByRole("slider")).toHaveCount(6);
  // Pixel rounding is expected; exact fields must accept canonical source bounds.
  for (const [index, start, end] of [[1, 0, 5], [2, 10, 15], [3, 24, 30]]) {
    await page.getByLabel(`${index}. bölüm başlangıcı (saniye)`).fill(String(start));
    await page.getByLabel(`${index}. bölüm bitişi (saniye)`).fill(String(end));
  }
  expect(server.writes).toHaveLength(0);
  const handle = page.getByRole("slider", { name: "2. bölüm başlangıcı" });
  await handle.scrollIntoViewIfNeeded(); let box = (await track.boundingBox())!;
  await gesture(page, handle, { x: box.x + box.width / 3, y: box.y + box.height / 2 }, { x: box.x + box.width * 0.4, y: box.y + box.height / 2 }, !!isMobile, true);
  await expect(handle).toHaveAttribute("aria-valuenow", "10");
  await track.scrollIntoViewIfNeeded(); box = (await track.boundingBox())!;
  await gesture(page, handle, { x: box.x + box.width / 3, y: box.y + box.height / 2 }, { x: box.x + box.width * 0.4, y: box.y + box.height / 2 }, !!isMobile);
  await expect.poll(async () => Number(await handle.getAttribute("aria-valuenow"))).toBeCloseTo(12, 0);
  await page.getByLabel("2. bölüm başlangıcı (saniye)").fill("10");
  await handle.focus(); await handle.press("ArrowRight"); await expect(handle).toHaveAttribute("aria-valuenow", "10.1");
  await handle.press("Shift+ArrowLeft"); await expect(handle).toHaveAttribute("aria-valuenow", "9.1");
  await page.getByLabel("2. bölüm başlangıcı (saniye)").fill("10");
  await track.scrollIntoViewIfNeeded(); box = (await track.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.65, box.y + box.height / 2);
  await expect.poll(() => page.locator("video").evaluate((node: HTMLVideoElement) => node.currentTime)).toBeCloseTo(19.5, 0);
  await expect.poll(() => page.locator("video").evaluate((node: HTMLVideoElement) => node.duration)).toBe(30);
  await card(page, "a.mp4").getByRole("button", { name: "Bölümleri kaydet" }).click();
  await expect(page.getByText("Bölümler kaydedildi.")).toBeVisible();
  expect(server.snapshot.montage.selections.a).toEqual([{ start: 0, end: 5 }, { start: 10, end: 15 }, { start: 24, end: 30 }]);
  await page.reload(); await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await expect(page.getByLabel("3. bölüm bitişi (saniye)")).toHaveValue("30");
  await page.getByLabel("1. bölüm bitişi (saniye)").fill("");
  await page.getByRole("link", { name: "Ayarlar", exact: true }).click();
  await page.getByRole("button", { name: "Vazgeç", exact: true }).click();
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("");
  await page.getByLabel("1. bölüm bitişi (saniye)").fill("5");
  await track.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await handle.focus(); await expect(handle).toBeFocused();
  if (process.env.CAPTURE_UI) await page.screenshot({ path: info.outputPath("timeline.png"), fullPage: true });
  expect(server.errors).toEqual([]);
});

test("media order/removal/restoration and immutable authenticated archive", async ({ page, isMobile }, info) => {
  const server = await fixture(page);
  if (process.env.CAPTURE_UI) await page.screenshot({ path: info.outputPath("media-actions.png"), fullPage: true });
  if (!isMobile) {
    await page.getByRole("button", { name: "b.mp4 sırasını sürükle" }).dragTo(page.getByRole("heading", { name: "a.mp4", exact: true }));
    await expect.poll(() => server.snapshot.montage.order).toEqual(["b", "a"]);
  }
  await page.getByRole("button", { name: "a.mp4 dosyasını paketten çıkar" }).click();
  await expect(page.getByRole("list", { name: "Montaj sırası" }).getByRole("heading", { name: "a.mp4", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Paketten çıkarılmış medya" }).getByRole("heading", { name: "a.mp4", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "a.mp4 dosyasını geri yükle" }).click();
  await expect.poll(() => server.snapshot.montage.order).toEqual(isMobile ? ["a", "b"] : ["b", "a"]);
  await page.getByRole("link", { name: "Tamamlanmış paketler", exact: true }).click();
  const link = page.getByRole("link", { name: /Orijinali indir/ }); await expect(link).toHaveAttribute("href", server.original);
  await expect(page.getByRole("button", { name: "Bölümleri kaydet" })).toHaveCount(0);
  await expect(page.getByLabel("Fotoğraf ve video seç")).toHaveCount(0);
  await expect(page.getByText("reel.mp4 — dosya mevcut değil")).toBeVisible();
  const download = page.waitForEvent("download"); await link.click(); expect((await download).suggestedFilename()).toBe("Çalışma.MP4");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(server.errors).toEqual([]);
});

test("native row drag previews before/after insertion without writing until drop", async ({ page, isMobile }, info) => {
  test.skip(!!isMobile, "Native drag uses mouse; mobile has no reorder control.");
  const server = await fixture(page);
  const list = page.getByRole("list", { name: "Montaj sırası" });
  const rowA = list.locator(":scope > li").filter({ has: page.getByRole("heading", { name: "a.mp4", exact: true }) });
  const rowB = list.locator(":scope > li").filter({ has: page.getByRole("heading", { name: "b.mp4", exact: true }) });
  const handle = page.getByRole("button", { name: "b.mp4 sırasını sürükle" });
  await handle.scrollIntoViewIfNeeded();
  const source = (await handle.boundingBox())!, target = (await rowA.boundingBox())!;
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await expect(rowB).toHaveAttribute("data-selected", "true");
  await page.mouse.up();
  await expect(rowB).not.toHaveAttribute("data-selected", "true");
  await page.mouse.down();
  await page.mouse.move(target.x + target.width - 10, target.y + target.height / 2, { steps: 8 });
  // Crossing into a new native drop target fires dragenter before dragover.
  await page.mouse.move(target.x + target.width - 10, target.y + target.height / 2);
  await expect(rowA).toHaveAttribute("data-drop-position", "after");
  expect(server.writes).toHaveLength(0);
  await page.mouse.move(target.x + 10, target.y + target.height / 2, { steps: 4 });
  await page.mouse.move(target.x + 10, target.y + target.height / 2);
  await expect(rowA).toHaveAttribute("data-drop-position", "before");
  await expect(rowB).toHaveAttribute("data-dragging", "true");
  expect(server.snapshot.montage.order).toEqual(["a", "b"]);
  if (process.env.CAPTURE_UI) await page.screenshot({ path: info.outputPath("media-drag-insertion.png"), fullPage: true });
  await page.mouse.up();
  await expect.poll(() => server.snapshot.montage.order).toEqual(["b", "a"]);
  await expect(list.locator("[data-selected], [data-dragging], [data-drop-position]")).toHaveCount(0);
  expect(server.errors).toEqual([]);
});

test("compact media cards flow left to right and wrap without filename or editor overflow", async ({ page, isMobile }, info) => {
  const server = await fixture(page, true);
  const photo = server.snapshot.media[2];
  photo.preview_url = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="180" height="120"><rect width="180" height="120" fill="#16665b"/></svg>')}`;
  for (let i = 0; i < 5; i++) {
    server.snapshot.media.push({ ...photo, media_id: `photo-${i}`, filename: i === 4 ? `${"uzun-dosya-adı".repeat(12)}.jpg` : `photo-${i}.jpg` });
    server.snapshot.montage.order.push(`photo-${i}`);
  }
  await page.reload();
  const list = page.getByRole("list", { name: "Montaj sırası" }), cards = list.locator(":scope > li");
  await expect(cards).toHaveCount(8);
  const first = (await cards.nth(0).boundingBox())!, second = (await cards.nth(1).boundingBox())!, last = (await cards.nth(7).boundingBox())!;
  for (const bounds of await cards.evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height))) expect(bounds).toBe(first.height);
  expect(await cards.evaluateAll(nodes => nodes.every(node => [...node.children].every(child => child.getBoundingClientRect().bottom <= node.getBoundingClientRect().bottom)))).toBe(true);
  const longTitle = cards.nth(7).getByRole("heading");
  expect(await longTitle.evaluate(node => getComputedStyle(node).whiteSpace)).toBe("nowrap");
  if (!isMobile) { expect(second.y).toBe(first.y); expect(second.x).toBeGreaterThan(first.x + first.width); }
  expect(last.y).toBeGreaterThan(first.y);
  const photoCard = cards.nth(2), preview = photoCard.getByRole("img");
  await preview.scrollIntoViewIfNeeded();
  await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(180);
  expect((await photoCard.boundingBox())!.width - (await preview.boundingBox())!.width).toBeLessThanOrEqual(34);
  expect(await list.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await expect(page.getByRole("group", { name: "Video zaman çizelgesi" })).toBeVisible();
  const expanded = (await cards.nth(0).boundingBox())!, listBounds = (await list.boundingBox())!;
  expect(expanded.width).toBeCloseTo(listBounds.width, 0);
  const neighbor = (await cards.nth(1).boundingBox())!;
  expect(neighbor.y).toBeGreaterThanOrEqual(expanded.y + expanded.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await list.scrollIntoViewIfNeeded();
  if (process.env.CAPTURE_UI) await page.screenshot({ path: info.outputPath("media-card-layout.png"), fullPage: true });
  expect(server.errors).toEqual([]);
});

test("photo duration, draft discard, playable saved reel and confirmed package cleanup", async ({ page }, info) => {
  const server = await fixture(page, true);
  const photoCard = card(page, "photo.jpg");
  const duration = page.getByRole("spinbutton", { name: "photo.jpg Gösterilme süresi (sn)" });
  await expect(duration).toHaveValue("3");
  await duration.fill("4.5");
  await photoCard.getByRole("button", { name: "Bölümleri kaydet" }).click();
  await expect(photoCard.getByRole("button", { name: "Bölümleri kaydet" })).toBeDisabled();
  expect(server.snapshot.media.find(m => m.media_id === "photo")!.effective_duration).toBe(4.5);
  await duration.fill("6");
  await photoCard.getByRole("button", { name: "Kaydedilmemiş değişiklikleri geri al" }).click();
  await expect(duration).toHaveValue("4.5");
  await duration.fill("7");
  await page.getByRole("button", { name: "Kaydedilmiş montajı render et" }).click();
  const reel = page.locator('video[aria-label="Kaydedilmiş Reel önizlemesi"]');
  await expect.poll(() => reel.evaluate((node: HTMLVideoElement) => node.duration)).toBe(30);
  await expect(page.getByRole("heading", { name: "Kaydedilmiş Reel önizlemesi · 30.00 s" })).toBeVisible();
  await expect(page.locator(".saved-reel-preview")).toHaveCount(1);
  expect(await page.locator(".saved-reel-preview").evaluate(node => !!(node.compareDocumentPosition(document.querySelector(".package-upload-controls")!) & Node.DOCUMENT_POSITION_PRECEDING))).toBe(true);
  await reel.evaluate((node: HTMLVideoElement) => node.play());
  await expect.poll(() => reel.evaluate((node: HTMLVideoElement) => node.currentTime)).toBeGreaterThan(0);
  await expect(duration).toHaveValue("7");
  expect(server.snapshot.media.find(m => m.media_id === "photo")!.effective_duration).toBe(4.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.CAPTURE_UI) await page.screenshot({ path: info.outputPath("saved-reel-photo-duration.png"), fullPage: true });
  const before = server.writes.length;
  page.once("dialog", dialog => { expect(dialog.message()).toContain("geri alınamaz"); void dialog.dismiss(); });
  await page.getByRole("button", { name: "Paketi temizle" }).click();
  expect(server.writes).toHaveLength(before);
  page.once("dialog", dialog => { void dialog.accept(); });
  await page.getByRole("button", { name: "Paketi temizle" }).click();
  await expect(page.getByText("Aktif paket yok. Medya yükleyerek yeni paket oluşturabilirsiniz.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Montaj sırası" })).toHaveCount(0);
  expect(server.errors).toEqual([]);
});

test("list requests no video until original viewer opens; Escape restores focus", async ({ page }) => {
  const mediaRequests: string[] = [];
  page.on("request", request => { if (/\/(original|preview)(\?|$)/.test(request.url())) mediaRequests.push(request.url()); });
  await fixture(page);
  expect(mediaRequests).toEqual([]);
  const trigger = page.getByRole("button", { name: "a.mp4 tam ekran görüntüle" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "a.mp4" });
  await expect(dialog.locator("video")).toHaveAttribute("src", /\/original\?/);
  await expect(dialog.getByRole("button", { name: "Tam ekranı kapat" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("fractional terminal endpoints stay exact with reachable End and touch handles", async ({ page, isMobile }) => {
  const server = await fixture(page);
  server.snapshot.media[0].source_duration = 6.1238;
  await page.reload();
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await page.getByRole("button", { name: "Bölüm ekle", exact: true }).click();
  const track = page.getByRole("group", { name: "Video zaman çizelgesi" });
  const end = page.getByRole("slider", { name: "1. bölüm bitişi", exact: true });
  await end.focus(); await end.press("End");
  await expect(end).toHaveAttribute("aria-valuenow", "6.1238");
  await track.scrollIntoViewIfNeeded();
  const box = (await end.boundingBox())!, bounds = (await track.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.x + box.width).toBeLessThanOrEqual((await card(page, "a.mp4").boundingBox())!.x + (await card(page, "a.mp4").boundingBox())!.width);
  await gesture(page, end, { x: box.x + box.width / 2, y: box.y + box.height / 2 }, { x: bounds.x + bounds.width + 15, y: box.y + box.height / 2 }, !!isMobile);
  await expect(end).toHaveAttribute("aria-valuenow", "6.1238");
});

test("SSE section completion keeps invalid sibling draft and empty save removes only saved preview", async ({ page }) => {
  const server = await fixture(page);
  await page.getByRole("button", { name: "b.mp4 bölümlerini düzenle" }).click();
  await page.getByRole("button", { name: "Bölüm ekle", exact: true }).click();
  await page.getByLabel("1. bölüm bitişi (saniye)").fill("");
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await page.getByRole("button", { name: "Bölüm ekle", exact: true }).click();
  await card(page, "a.mp4").getByRole("button", { name: "Bölümleri kaydet" }).click();
  await expect(page.getByText("Bölüm önizlemesi sırada.")).toBeVisible();
  const revision = server.snapshot.content_revision;
  server.snapshot.media[0].section_preview = { status: "ready", generation: "saved-1", url: "/api/packages/active/media/a/sections/preview?generation=saved-1", duration: 1 };
  server.snapshot.view_revision++;
  await invalidateLive(page, ["package:1"]);
  const savedPreview = page.getByLabel("a.mp4 Kaydedilmiş bölüm önizlemesi", { exact: true });
  await expect(savedPreview).toBeVisible();
  expect(server.snapshot.content_revision).toBe(revision);
  await page.getByRole("button", { name: "1. bölümü kaldır" }).click();
  await expect(savedPreview).toBeVisible();
  await expect(card(page, "a.mp4").getByText("Önizleme kaydedilmemiş değişiklikleri içermez.")).toBeVisible();
  await card(page, "a.mp4").getByRole("button", { name: "Bölümleri kaydet" }).click();
  await expect(savedPreview).toHaveCount(0);
  await expect(page.getByLabel("a.mp4 video önizlemesi")).toHaveAttribute("src", /\/original\?/);
  await page.getByRole("button", { name: "b.mp4 bölümlerini düzenle" }).click();
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("");
  expect(server.writes).toHaveLength(2);
  expect(server.errors).toEqual([]);
});
