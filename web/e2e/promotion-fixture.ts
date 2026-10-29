import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { packageSnapshot } from "../src/packages/testFixtures";
import { client, dashboard, setupState } from "../src/test/fixtures";
import { installLiveStream } from "./live-fixture";

export async function installPromotionFixture(page: Page, paired = true, tours = false, setupReady = true) {
  await installLiveStream(page, true, tours);
  const bytes = readFileSync(fileURLToPath(new URL("./fixtures/timeline.mp4", import.meta.url)));
  const editor = packageSnapshot(), data = dashboard(), errors: string[] = [];
  editor.package.folder_name = "Haftanın antrenmanı";
  editor.package.created_at = "2026-10-26T09:00:00Z";
  editor.media[0].filename = "Antrenman.mp4";
  editor.media[1].filename = "Teknik çalışma.mp4";
  for (const media of editor.media) { media.uploaded_at = "2026-10-26T09:10:00Z"; media.effective_duration = 15; }
  for (const clip of editor.montage.clips) clip.effective_duration = 15;
  editor.montage.selections = { a: [{ start: 0, end: 15 }], b: [{ start: 0, end: 15 }] };
  editor.montage.combined_duration = 30;
  editor.render_status = "ready"; editor.render_stale = false;
  editor.render_duration = 30; editor.render_preview_url = "/api/demo/preview";
  data.package = editor.package;
  data.generated_at = "2026-10-28T09:00:00Z";
  data.plan.anchor_date = "2026-10-26";
  data.plan.anchor_time = "12:00:00";
  data.next_slot = { kind: "regular", due_at: "2026-11-09T09:00:00Z" };
  const completedName = `${editor.package.folder_name}-completed`;
  data.instagram.username = "ornek_dogo";
  data.pending_actions = [{ occurrence_id: 1, review_id: 2, version: 1, state: "review_ready", package_folder: editor.package.folder_name, due_at: data.generated_at }];
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const path = decodeURIComponent(new URL(route.request().url()).pathname);
    const json = (value: unknown, status = 200) => route.fulfill({ json: value, status });
    if (path.endsWith("/thumbnail")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#172b4b"/><path d="M80 120L140 60l60 60 40-40" fill="none" stroke="#5195ff" stroke-width="5"/></svg>' });
    if (path.endsWith("/preview") || path.endsWith("/original")) {
      const range = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/);
      const start = range ? Number(range[1]) : 0, end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
      return route.fulfill({ status: range ? 206 : 200, body: bytes.subarray(start, end + 1), headers: {
        "Content-Type": "video/mp4", "Accept-Ranges": "bytes",
        ...(range ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` } : {}),
      } });
    }
    if (path === "/api/compat") return json({ api_version: "0.1.0" });
    if (path === "/api/pairing/me") return json({ ...client, name: "Örnek çalışma alanı" }, paired ? 200 : 401);
    if (path === "/api/pairing/validate") { paired = true; return json({}); }
    if (path === "/api/setup") return json(setupState(setupReady ? undefined : "instagram"));
    if (path === "/api/dashboard") return json(data);
    if (path === "/api/packages/active/editor") return json(editor);
    if (path === "/api/media/upload-limits") return json({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 });
    if (path === "/api/packages") return json([{ ...editor.package, folder_name: completedName, status: "completed" }]);
    if (path === `/api/packages/${completedName}`) return json({ folder_name: completedName, caption: "Birlikte çalış, birlikte geliş. #aikido", media: [], order: [], render_revision: "sample", artifacts: [{ artifact_ref: "render/reel.mp4", kind: "render", filename: "reel.mp4", content_type: "video/mp4", available: true, url: "/api/demo/preview", preview_url: "/api/demo/preview" }] });
    if (path === "/api/reviews/2") return json({ review: { id: 2, occurrence_id: 1, version: 1, package_folder: editor.package.folder_name, revision_digest: "sample", caption: "Birlikte çalış, birlikte geliş. #aikido", status: "pending", created_at: data.generated_at }, render_ready: true, preview_url: "/api/demo/preview", next_regular_at: data.next_slot?.due_at });
    if (path === "/api/settings/plan") return json(data.plan);
    if (path === "/api/meta/status") return json({ health: "healthy", ig_username: "ornek_dogo" });
    if (path === "/api/settings/branding") return json({ logo_asset: null, caption_template: "Birlikte çalış, birlikte geliş. #aikido", intro_asset: null, intro_duration: null, outro_asset: null, outro_duration: null });
    if (path === "/api/settings/reminders") return json({ interval_minutes: 360, delivery_start: "08:00:00", delivery_end: "22:00:00", timezone: "Europe/Istanbul" });
    if (path === "/api/setup/consent") return json({ version: 1, text: "Medya paylaşımı için gerekli izinleri aldım.", accepted_at: data.generated_at });
    if (path === "/api/activity") return json({ events: [], next_cursor: null });
    errors.push(`Unexpected request: ${route.request().method()} ${path}`);
    return json({}, 404);
  });
  return { errors };
}
