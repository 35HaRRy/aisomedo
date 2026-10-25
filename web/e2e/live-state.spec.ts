import { test, expect, type Page } from "@playwright/test";
import { packageSnapshot } from "../src/packages/testFixtures";
import { client, dashboard, setupState } from "../src/test/fixtures";
import { installLiveStream, invalidateLive } from "./live-fixture";

const saveCard = (page: Page, id: string) => page.getByRole("list", { name: "Montaj sırası" }).locator(":scope > li").filter({ has: page.getByRole("heading", { name: `${id}.mp4`, exact: true }) }).getByRole("button", { name: "Bölümleri kaydet" });

function server() {
  const snapshot = packageSnapshot(), reads: string[] = [], writes: unknown[] = [];
  async function attach(page: Page, ready = true) {
    await installLiveStream(page, ready);
    await page.route(url => url.pathname.startsWith("/api/"), async route => {
      const path = new URL(route.request().url()).pathname;
      const json = (body: unknown, status = 200) => route.fulfill({ json: body, status });
      if (route.request().method() === "GET") reads.push(path);
      if (path === "/api/compat") return json({ api_version: "0.1.0" });
      if (path === "/api/pairing/me") return json(client);
      if (path === "/api/setup") return json(setupState());
      if (path === "/api/dashboard") return json({ ...dashboard(), package: snapshot.package });
      if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
      if (path === "/api/packages/active/editor") return json(snapshot);
      if (path === "/api/packages/active/edits") {
        const body = route.request().postDataJSON(); writes.push(body);
        const conflicts = body.changes.flatMap((change: { key: string; base: unknown; proposed: unknown }) => {
          const current = { ranges: snapshot.montage.selections[change.key.slice(6)] ?? [] };
          return JSON.stringify(current) === JSON.stringify(change.base) || JSON.stringify(current) === JSON.stringify(change.proposed)
            ? [] : [{ key: change.key, current }];
        });
        if (conflicts.length) return json({ detail: { code: "edit_conflict", content_revision: snapshot.content_revision, conflicts } }, 409);
        for (const change of body.changes) snapshot.montage.selections[change.key.slice(6)] = change.proposed.ranges;
        snapshot.content_revision++; return json(snapshot);
      }
      return json({}, 404);
    });
    await page.goto("/#/package");
    if (ready) await expect(page.getByRole("button", { name: "a.mp4 dosyasını sağa taşı" })).toBeEnabled();
  }
  return { snapshot, reads, writes, attach };
}

async function edit(page: Page, id: string, end: string) {
  await page.getByRole("button", { name: `${id}.mp4 bölümlerini düzenle` }).click();
  if (!await page.getByLabel("1. bölüm bitişi (saniye)").count()) await page.getByRole("button", { name: "Bölüm ekle" }).click();
  await page.getByLabel("1. bölüm bitişi (saniye)").fill(end);
}
async function durableEnd(page: Page) {
  return page.evaluate(() => new Promise<string | null>((resolve, reject) => {
    const request = indexedDB.open("dojo-package-drafts", 1);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const read = db.transaction("drafts").objectStore("drafts").get(JSON.stringify([location.origin, 1, 1]));
      read.onsuccess = () => { resolve(read.result?.inputs.a?.[0]?.end ?? null); db.close(); };
      read.onerror = () => { reject(read.error); db.close(); };
    };
  }));
}

test("real IndexedDB preserves incomplete input across reload and ten idle minutes never poll", async ({ page }) => {
  await page.clock.install();
  const state = server(); await state.attach(page);
  await edit(page, "a", "");
  await expect.poll(() => durableEnd(page)).toBe("");
  await page.reload();
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("");
  const reads = state.reads.length;
  for (let i = 0; i < 40; i++) {
    await page.evaluate(() => window.dispatchEvent(new Event("fixture:heartbeat")));
    await page.clock.fastForward(15_000);
  }
  expect(state.reads).toHaveLength(reads); expect(state.writes).toHaveLength(0);
  await page.evaluate(() => window.dispatchEvent(new Event("fixture:disconnect")));
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toBeDisabled();
  await expect.poll(() => durableEnd(page)).toBe("");
});

test("restored input stays disabled until ready plus snapshot synchronization", async ({ page }) => {
  const state = server(); await state.attach(page, false);
  // Seed through the actual repository, not a mocked storage implementation.
  await page.evaluate(async () => {
    const path = "/src/packages/drafts.ts";
    const { writeDraft } = await import(path);
    await writeDraft({ origin: location.origin, clientId: 1, packageId: 1 }, 0, {
      schemaVersion: 1, localRevision: 0, folderName: "02-10-2026 13-00", baseContentRevision: 1,
      groups: { "video:a": { base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: "" }] } } },
      inputs: { a: [{ start: "0", end: "" }] }, uncertain: false,
    });
  });
  await page.reload();
  await expect(page.getByRole("group", { name: "Canlı çalışma alanı" })).toHaveAttribute("disabled", "");
  await expect.poll(() => durableEnd(page)).toBe("");
  expect(state.reads.filter(path => path.endsWith("/editor"))).toHaveLength(0);
  await page.evaluate(() => window.dispatchEvent(new Event("fixture:ready")));
  await expect(page.getByRole("button", { name: "a.mp4 dosyasını sağa taşı" })).toBeEnabled();
  await page.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
  await expect(page.getByLabel("1. bölüm bitişi (saniye)")).toHaveValue("");
  expect(state.writes).toHaveLength(0);
});

test("IndexedDB competing writes atomically reject one tab rather than replacing its draft", async ({ page }) => {
  const state = server(); await state.attach(page);
  const result = await page.evaluate(async () => {
    const path = "/src/packages/drafts.ts";
    const { writeDraft, readDraft } = await import(path);
    const key = { origin: location.origin, clientId: 1, packageId: 1 };
    const draft = { schemaVersion: 1, localRevision: 0, folderName: "02-10-2026 13-00", baseContentRevision: 1,
      groups: { "video:a": { base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 5 }] } } },
      inputs: { a: [{ start: "0", end: "5" }] }, uncertain: false };
    const settled = await Promise.allSettled([writeDraft(key, 0, draft), writeDraft(key, 0, { ...draft, uncertain: true })]);
    return { statuses: settled.map(value => value.status).sort(), saved: await readDraft(key) };
  });
  expect(result.statuses).toEqual(["fulfilled", "rejected"]);
  expect(result.saved.localRevision).toBe(1); expect(result.saved.inputs.a[0].end).toBe("5");
});

test("two profiles merge different videos and same-video conflict rejects the whole batch", async ({ browser, baseURL }) => {
  const state = server();
  const first = await browser.newContext({ baseURL }), second = await browser.newContext({ baseURL });
  try {
    const a = await first.newPage(), b = await second.newPage();
    await state.attach(a); await state.attach(b);
    await edit(a, "a", "5"); await edit(b, "b", "6");
    await saveCard(a, "a").click();
    await expect(a.getByText("Bölümler kaydedildi.")).toBeVisible();
    await invalidateLive(b);
    await expect(saveCard(b, "b")).toBeEnabled();
    await saveCard(b, "b").click();
    await expect(b.getByText("Bölümler kaydedildi.")).toBeVisible();
    expect(state.snapshot.montage.selections).toEqual({ a: [{ start: 0, end: 5 }], b: [{ start: 0, end: 6 }] });
    const rejection = await b.evaluate(async () => {
      const response = await fetch("/api/packages/active/edits", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        expected_package_id: 1, expected_folder_name: "02-10-2026 13-00", base_content_revision: 1,
        changes: [
          { key: "video:a", base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 9 }] } },
          { key: "video:b", base: { ranges: [{ start: 0, end: 6 }] }, proposed: { ranges: [{ start: 0, end: 8 }] } },
        ],
      }) });
      return response.status;
    });
    expect(rejection).toBe(409);
    expect(state.snapshot.montage.selections.b).toEqual([{ start: 0, end: 6 }]);
    await invalidateLive(a);
    await a.getByLabel("1. bölüm bitişi (saniye)").fill("7");
    await b.getByRole("button", { name: "a.mp4 bölümlerini düzenle" }).click();
    await b.getByLabel("1. bölüm bitişi (saniye)").fill("8");
    await saveCard(a, "a").click();
    await expect(a.getByText("Bölümler kaydedildi.")).toBeVisible(); await invalidateLive(b);
    await expect(b.getByRole("region", { name: "video:a çakışması" })).toBeVisible();
    await expect(saveCard(b, "a")).toBeDisabled();
    expect(state.writes).toHaveLength(4);
  } finally { await first.close(); await second.close(); }
});
