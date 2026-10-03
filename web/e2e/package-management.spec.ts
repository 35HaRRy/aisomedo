import { test, expect, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { packageSnapshot } from "../src/packages/testFixtures";
import { client, dashboard, setupState } from "../src/test/fixtures";

const bytes = readFileSync(fileURLToPath(new URL("./fixtures/timeline.mp4", import.meta.url)));
async function fixture(page: Page) {
  const snapshot = packageSnapshot(); const writes: unknown[] = [], errors: string[] = [];
  const archived = "Çalışma-completed", original = `/api/packages/${encodeURIComponent(archived)}/artifacts?artifact_ref=media%2Fa%2Foriginal.MP4&download=true`;
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()), path = decodeURIComponent(url.pathname), method = route.request().method();
    const json = (value: unknown, status = 200) => route.fulfill({ status, json: value });
    if (path.endsWith("/preview") || path.endsWith("/artifacts")) {
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
    if (path === "/api/dashboard") return json({ ...dashboard(), package: snapshot.package });
    if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (path === "/api/packages/active/editor") return json(snapshot);
    if (path === "/api/packages") return json([{ ...snapshot.package, id: 9, folder_name: archived, status: "completed" }]);
    if (path === `/api/packages/${archived}`) return json({ folder_name: archived, media: [{ ...snapshot.media[0], filename: "Çalışma.MP4", preview_url: null, artifacts: [{ artifact_ref: "media/a/original.MP4", kind: "original", filename: "Çalışma.MP4", content_type: "video/mp4", available: true, url: original, preview_url: null }] }], order: ["a"], caption: null, render_revision: null, artifacts: [{ artifact_ref: "render/reel.mp4", kind: "render", filename: "reel.mp4", content_type: "video/mp4", available: false, url: null, preview_url: null }] });
    if (method !== "GET" && path.startsWith("/api/packages/active/")) {
      const body = route.request().postDataJSON(); writes.push({ path, body });
      if (path.endsWith("/selections")) snapshot.montage.selections = body.selections;
      else if (path.endsWith("/order")) snapshot.montage.order = body.order;
      else {
        const media = snapshot.media.find(m => path.includes(`/media/${m.media_id}/`));
        if (!media) { errors.push(`unexpected mutation ${path}`); return json({}, 404); }
        if (path.endsWith("/remove")) { media.status = "removed"; media.removed_position = snapshot.montage.order.indexOf(media.media_id); snapshot.montage.order = snapshot.montage.order.filter(id => id !== media.media_id); }
        else if (path.endsWith("/restore")) { media.status = "finalized"; snapshot.montage.order.splice(media.removed_position ?? 0, 0, media.media_id); }
        else errors.push(`unexpected mutation ${path}`);
      }
      for (const media of snapshot.media) media.effective_duration = snapshot.montage.selections[media.media_id]?.reduce((sum, r) => sum + r.end - r.start, 0) ?? 30;
      snapshot.montage.combined_duration = snapshot.media.filter(m => m.status === "finalized").reduce((sum, m) => sum + (m.effective_duration ?? 0), 0);
      snapshot.render_stale = true; return json(snapshot.montage);
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
  await page.getByRole("button", { name: "Bölümleri kaydet" }).click();
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

test("media order/removal/restoration and immutable authenticated archive", async ({ page, isMobile }) => {
  const server = await fixture(page);
  if (isMobile) await page.getByRole("button", { name: "b.mp4 dosyasını yukarı taşı" }).click();
  else await page.getByRole("button", { name: "b.mp4 sırasını sürükle" }).dragTo(page.getByRole("heading", { name: "a.mp4", exact: true }));
  await expect.poll(() => server.snapshot.montage.order).toEqual(["b", "a"]);
  await page.getByRole("button", { name: "a.mp4 dosyasını paketten çıkar" }).click();
  await page.getByRole("button", { name: "a.mp4 dosyasını geri yükle" }).click();
  await expect.poll(() => server.snapshot.montage.order).toEqual(["b", "a"]);
  await page.getByRole("button", { name: "Tamamlanmış paketler", exact: true }).click();
  const link = page.getByRole("link", { name: /Orijinali indir/ }); await expect(link).toHaveAttribute("href", server.original);
  await expect(page.getByRole("button", { name: "Bölümleri kaydet" })).toHaveCount(0);
  await expect(page.getByLabel("Fotoğraf ve video seç")).toHaveCount(0);
  await expect(page.getByText("reel.mp4 — dosya mevcut değil")).toBeVisible();
  const download = page.waitForEvent("download"); await link.click(); expect((await download).suggestedFilename()).toBe("Çalışma.MP4");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(server.errors).toEqual([]);
});
