import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { client, dashboard, emptyEditor, setupState } from "../src/test/fixtures";

const bytes = readFileSync(fileURLToPath(new URL("./fixtures/timeline.mp4", import.meta.url)));
async function fixture(page: Page, continuation = false) {
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
    if (path === "/api/reviews/2") return json({ review, render_ready: review.status === "pending", preview_url: review.status === "pending" ? preview : null, next_regular_at: "2026-08-17T07:00:00Z" });
    if (path.startsWith("/api/reviews/2/") && route.request().method() === "POST") {
      writes.push({ path, body: route.request().postDataJSON() });
      review.status = status === 409 ? "skipped" : path.endsWith("/approve") ? "approved" : path.endsWith("/skip") ? "skipped" : "rescheduled";
      state.pending_actions = [];
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
  return { writes, errors, preview, setStatus: (value: number) => { status = value; },
    setPublication: (value: typeof publication) => { publication = value; } };
}

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

test("Istanbul reschedule and other-device conflict cannot replay action", async ({ page }) => {
  const server = await fixture(page);
  await page.getByRole("button", { name: "Başka zamana planla" }).click();
  await page.getByLabel("Yeni Yayın Zamanı (İstanbul)").fill("2000-08-04T12:30");
  await expect(page.getByRole("button", { name: "Yeni zamanı onayla", exact: true })).toBeDisabled();
  await page.getByLabel("Yeni Yayın Zamanı (İstanbul)").fill("2099-08-04T12:30");
  server.setStatus(409);
  await page.getByRole("button", { name: "Yeni zamanı onayla", exact: true }).click();
  await expect(page.getByText("Bu inceleme başka bir cihazda tamamlanmış veya artık mevcut değil.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Onayla ve yayınla" })).toHaveCount(0);
  expect(server.writes).toEqual([{ path: "/api/reviews/2/reschedule", body: { version: 3, new_due_at: "2099-08-04T12:30:00+03:00" } }]);
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
