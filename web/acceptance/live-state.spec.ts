import { test, expect, type BrowserContext } from "@playwright/test";
import { readFileSync } from "node:fs";
import type { ActiveEditorOut } from "../src/api/openapi";

test("live profiles merge drafts and recover without polling through the gateway", async ({ browser, playwright }) => {
  const baseURL = process.env.ACCEPTANCE_BASE_URL;
  if (!baseURL || new URL(baseURL).hostname !== "dojo.acceptance.test" || !process.env.ACCEPTANCE_SEED_FILE) {
    throw new Error("Requires the disposable acceptance stack, private seed file, and /evidence mount");
  }
  const seed = JSON.parse(readFileSync(process.env.ACCEPTANCE_SEED_FILE, "utf8"));
  const contexts: BrowserContext[] = [];
  const fixtures = await playwright.request.newContext({ baseURL: process.env.ACCEPTANCE_FIXTURES_URL });
  try {
    for (const [index, code] of [seed.live_browser_a, seed.live_browser_b].entries()) {
      expect(code, "Fresh live-state pairing code from acceptance.bootstrap seed").toBeTruthy();
      const context = await browser.newContext({ baseURL }); contexts.push(context);
      expect((await context.request.post("/api/pairing/validate", { data: { code, kind: "browser", name: `Live profile ${index}` } })).ok()).toBe(true);
    }
    const [first, second] = contexts;
    expect((await first.request.get("/api/packages/active/editor")).status()).toBe(404);
    const a = await first.newPage(), b = await second.newPage();
    await a.goto("/#/package"); await b.goto("/#/package");
    const bytes = readFileSync("e2e/fixtures/timeline.mp4");
    await a.getByLabel("Fotoğraf ve video seç", { exact: true }).setInputFiles([
      { name: "live-a.mp4", mimeType: "video/mp4", buffer: bytes },
      { name: "live-b.mp4", mimeType: "video/mp4", buffer: bytes },
    ]);
    // These rows arrive through worker-originated invalidations, never a page reload.
    for (const page of [a, b]) for (const name of ["live-a.mp4", "live-b.mp4"]) {
      await expect(page.getByRole("region", { name: "Aktif paket medyası", exact: true }).getByRole("heading", { name, exact: true })).toBeVisible();
    }
    const baseline = await (await first.request.get("/api/packages/active/editor")).json() as ActiveEditorOut;
    const idA = baseline.media.find(media => media.filename === "live-a.mp4")!.media_id;
    const idB = baseline.media.find(media => media.filename === "live-b.mp4")!.media_id;
    for (const [page, name, end] of [[a, "live-a.mp4", "5"], [b, "live-b.mp4", "6"]] as const) {
      await page.getByRole("button", { name: `${name} bölümlerini düzenle` }).click();
      await page.getByRole("button", { name: "Bölüm ekle" }).click();
      await page.getByLabel("1. bölüm bitişi (saniye)").fill(end);
    }
    await a.getByRole("listitem").filter({ hasText: "live-a.mp4" })
      .getByRole("button", { name: "Bölümleri kaydet" }).click();
    await expect(a.getByText("Bölümler kaydedildi.")).toBeVisible();
    // Let the first save's worker previews finish before submitting the second
    // draft: their invalidations temporarily disable writes during live resync.
    await expect.poll(async () => {
      const snapshot = await (await second.request.get("/api/packages/active/editor")).json() as ActiveEditorOut;
      return snapshot.media.every(media => !!media.thumbnail_url)
        && snapshot.media.find(media => media.media_id === idA)?.section_preview?.status === "ready";
    }, { timeout: 60_000 }).toBe(true);
    await expect(b.getByRole("listitem").filter({ hasText: "live-a.mp4" })).toContainText("5.00 s");
    await b.getByRole("listitem").filter({ hasText: "live-b.mp4" })
      .getByRole("button", { name: "Bölümleri kaydet" }).click();
    await expect(b.getByText("Bölümler kaydedildi.")).toBeVisible();
    const merged = await (await first.request.get("/api/packages/active/editor")).json() as ActiveEditorOut;
    expect(merged.montage.selections[idA]).toEqual([{ start: 0, end: 5 }]);
    expect(merged.montage.selections[idB]).toEqual([{ start: 0, end: 6 }]);
    const rejected = await second.request.put("/api/packages/active/edits", { data: {
      expected_package_id: baseline.package.id, expected_folder_name: baseline.package.folder_name,
      base_content_revision: baseline.content_revision, changes: [
        { key: `video:${idA}`, base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 9 }] } },
        { key: `video:${idB}`, base: { ranges: [{ start: 0, end: 6 }] }, proposed: { ranges: [{ start: 0, end: 8 }] } },
      ],
    } });
    expect(rejected.status()).toBe(409);
    expect(((await (await first.request.get("/api/packages/active/editor")).json()) as ActiveEditorOut).montage.selections[idB]).toEqual([{ start: 0, end: 6 }]);
    await a.getByLabel("1. bölüm bitişi (saniye)").fill("");
    await expect.poll(() => a.evaluate(() => new Promise<string | null>((resolve, reject) => {
      const request = indexedDB.open("dojo-package-drafts", 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result, cursor = db.transaction("drafts").objectStore("drafts").openCursor();
        cursor.onsuccess = () => {
          const value = cursor.result;
          if (!value) { db.close(); resolve(null); return; }
          const rows = Object.values(value.value.inputs) as { end: string }[][];
          if (rows.some(items => items.some(item => item.end === ""))) { db.close(); resolve(""); }
          else value.continue();
        };
      };
    }))).toBe("");
    await first.setOffline(true);
    await expect(a.getByLabel("1. bölüm bitişi (saniye)")).toBeDisabled();
    await first.setOffline(false); await a.reload();
    await a.getByRole("button", { name: "live-a.mp4 bölümlerini düzenle" }).click();
    await expect(a.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("");
    // An idle worker may still have queued jobs between ticks. Wait for every
    // thumbnail and saved section preview, not just the current worker phase.
    await expect.poll(async () => {
      const snapshot = await (await first.request.get("/api/packages/active/editor")).json() as ActiveEditorOut;
      return snapshot.media.length === 2 && snapshot.media.every(media =>
        !!media.thumbnail_url && media.section_preview?.status === "ready");
    }, { timeout: 60_000 }).toBe(true);
    await expect.poll(async () => (await (await fixtures.get("/worker-health")).json()).phase).toBe("idle");
    await expect(a.getByRole("button", { name: "live-a.mp4 sırasını sürükle" })).toBeEnabled();
    let idleReads = 0, lastReadAt = Date.now();
    a.on("request", request => {
      if (request.method() === "GET" && new URL(request.url()).pathname.startsWith("/api/") && !request.url().endsWith("/api/events")) {
        idleReads++; lastReadAt = Date.now();
      }
    });
    // Section-preview jobs finish after the reload and invalidate the editor; let
    // that worker-originated burst settle before measuring an idle window.
    await expect.poll(() => Date.now() - lastReadAt, { timeout: 30_000 }).toBeGreaterThan(3_000);
    idleReads = 0;
    // Intentional observation window: longer than the removed five-second polling interval.
    await a.waitForTimeout(12_000);
    expect(idleReads).toBe(0);
    await a.screenshot({ path: "/evidence/live-state-desktop.png", fullPage: true });
    await a.setViewportSize({ width: 390, height: 844 });
    await a.screenshot({ path: "/evidence/live-state-mobile.png", fullPage: true });
    const identity = await (await second.request.get("/api/pairing/me")).json();
    expect((await first.request.post(`/api/pairing/clients/${identity.id}/revoke`)).ok()).toBe(true);
    await expect(b.getByLabel("Eşleştirme kodu", { exact: true })).toBeVisible();
    const current = await (await first.request.get("/api/packages/active/editor")).json() as ActiveEditorOut;
    expect(current.package.id).toBe(baseline.package.id);
    expect((await first.request.post("/api/packages/active/clear", {
      headers: { "If-Match": `"${current.package.id}:${current.content_revision}"` },
      data: { expected_package_id: current.package.id, expected_folder_name: current.package.folder_name, confirmed: true },
    })).ok()).toBe(true);
  } finally { for (const context of contexts) await context.close(); await fixtures.dispose(); }
});
