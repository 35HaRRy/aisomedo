import { afterEach, expect, it, vi } from "vitest";
import { api, request } from "./client";

it("olderResponseCannotReplaceNewerState", async () => {
  const replies: ((response: Response) => void)[] = [];
  vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { replies.push(resolve); }));
  const older = request<{ caption: string }>("/api/packages/active/editor");
  const rejection = expect(older).rejects.toMatchObject({ superseded: true });
  const newer = request<{ caption: string }>("/api/packages/active/editor");
  const response = (caption: string, version: number) => new Response(JSON.stringify({ caption }), {
    headers: { "X-Resource-Key": "package:99", "X-Resource-Version": String(version) },
  });
  replies[1](response("new", 8));
  expect(await newer).toEqual({ caption: "new" });
  replies[0](response("old", 7));
  await rejection;
});

afterEach(() => vi.useRealTimers());

it("pairs a browser with cookies and no stored token", async () => {
  let sent: RequestInit | undefined;
  vi.stubGlobal("fetch", async (_url: string, init: RequestInit) => {
    sent = init;
    return new Response(JSON.stringify({ client_id: 1, kind: "browser" }));
  });
  await api.pair({ code: "ABC", name: "Dojo", kind: "browser" });
  expect(sent?.credentials).toBe("same-origin");
  expect(JSON.parse(String(sent?.body))).toEqual({ code: "ABC", name: "Dojo", kind: "browser" });
  expect(localStorage.length).toBe(0);
});

it.each([401, 429, 500])("preserves HTTP status %i without server error copy", async status => {
  vi.stubGlobal("fetch", async () => new Response("private error", { status }));
  await expect(request("/api/dashboard")).rejects.toMatchObject({ status });
});

it("bounds hung requests to ten seconds", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", (_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
  }));
  const result = expect(request("/api/dashboard")).rejects.toMatchObject({ status: 0 });
  await vi.advanceTimersByTimeAsync(10000);
  await result;
});

it("keeps caller cancellation distinct from network errors", async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(request("/api/dashboard", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
});

it("sends onboarding operations with cookies and typed bodies", async () => {
  const fetcher = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  await api.setup(); await api.consent(); await api.acceptConsent(3); await api.skipCards();
  await api.branding(); await api.patchBranding({ caption_template: "Dojo" });
  await api.plan(); await api.savePlan({ anchor_date: "2026-10-05", anchor_time: "10:00", enabled: false });
  await api.instagram(); await api.connectInstagramToken("private-token");
  await api.startOAuth(); await api.oauthAttempt(7); await api.selectInstagramAccount(7, "ig-1");
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([
    "/api/setup", "/api/setup/consent", "/api/setup/consent/accept", "/api/setup/cards/skip",
    "/api/settings/branding", "/api/settings/branding", "/api/settings/plan", "/api/settings/plan",
    "/api/meta/status", "/api/meta/instagram/token", "/api/meta/oauth/start",
    "/api/meta/oauth/attempts/7", "/api/meta/oauth/attempts/7/select",
  ]);
  expect(fetcher.mock.calls[2][1]).toMatchObject({ method: "POST", body: '{"version":3}', credentials: "same-origin" });
  expect(fetcher.mock.calls[9][1]).toMatchObject({ method: "POST", body: '{"access_token":"private-token"}' });
  expect(localStorage.length).toBe(0);
});

it("uploads raw file without JSON content type", async () => {
  const fetcher = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  const file = new File(["image"], "logo.png", { type: "image/png" });
  await api.uploadBranding(file);
  expect(fetcher.mock.calls[0][0]).toBe("/api/settings/branding/assets");
  expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", body: file });
  expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty("Content-Type", "application/json");
});

it("sends upload operations with encoded IDs, raw ranges, and cookies", async () => {
  const fetcher = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  const body = new Blob(["media"]);
  await api.uploadLimits();
  await api.startUpload({ filename: "dojo.mov", content_type: "video/quicktime", declared_size_bytes: 5 });
  await api.uploadStatus("id/1");
  await api.uploadRange("id/1", 2, "a+b", body);
  await api.completeUpload("id/1");
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([
    "/api/media/upload-limits", "/api/media/uploads", "/api/media/uploads/id%2F1",
    "/api/media/uploads/id%2F1/ranges?offset=2&checksum_sha256=a%2Bb", "/api/media/uploads/id%2F1/complete",
  ]);
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST", body: '{"filename":"dojo.mov","content_type":"video/quicktime","declared_size_bytes":5}' });
  expect(fetcher.mock.calls[3][1]).toMatchObject({ method: "PUT", body, headers: { "Content-Type": "application/octet-stream" } });
  expect(fetcher.mock.calls[4][1]).toMatchObject({ method: "POST" });
  expect(fetcher.mock.calls.every(call => call[1].credentials === "same-origin")).toBe(true);
});

it("retains only textual JSON error detail", async () => {
  vi.stubGlobal("fetch", async () => new Response('{"detail":"chunk checksum mismatch"}', { status: 400 }));
  await expect(request("/api/media/uploads")).rejects.toMatchObject({ status: 400, detail: "chunk checksum mismatch" });
});

it("preserves typed edit conflicts without retaining unrelated error bodies", async () => {
  const conflict = { code: "edit_conflict", content_revision: 7,
    conflicts: [{ key: "video:a", current: { ranges: [{ start: 0, end: 5 }] } }] };
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: conflict }), { status: 409 }));
  await expect(request("/api/packages/active/edits")).rejects.toMatchObject({ status: 409, conflict });
});

it("sends conflict resolution with cookies, encoded ID and explicit overwrite confirmation", async () => {
  const fetcher = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  await api.resolveUpload("id/1", { decision: "keep_selected", target_media_id: "target", confirmed_overwrite: true, apply_to_all: true });
  expect(fetcher.mock.calls[0][0]).toBe("/api/media/uploads/id%2F1/resolve");
  expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", method: "POST" });
  expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toEqual({ decision: "keep_selected", target_media_id: "target", confirmed_overwrite: true, apply_to_all: true });
});

it.each(["private body", '{"detail":[{"input":"secret"}]}', "{"])("ignores unstructured error body %s", async body => {
  vi.stubGlobal("fetch", async () => new Response(body, { status: 422 }));
  await expect(request("/api/media/uploads")).rejects.toMatchObject({ status: 422, detail: undefined });
});

it("sends package editing and history through session-aware encoded URLs", async () => {
  const fetcher = vi.fn(async (_url: string, _init: RequestInit) => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  const folder = "Çalışma 1";
  const selections = { a: [{ start: 0, end: 5 }, { start: 10, end: 15 }] };
  const expected = { package: { id: 12 }, content_revision: 7 };
  await api.packageEditor();
  await api.saveSelections({ expected_folder_name: folder, selections }, expected);
  await api.saveOrder(["b", "a"], folder, expected);
  await api.removeMedia("id/1", folder, expected); await api.restoreMedia("id/1", folder, expected);
  await api.completedPackages(); await api.completedPackage(folder);
  const encoded = encodeURIComponent(folder);
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([
    "/api/packages/active/editor", "/api/packages/active/selections", "/api/packages/active/order",
    `/api/packages/active/media/id%2F1/remove?expected_folder_name=${encoded}`,
    `/api/packages/active/media/id%2F1/restore?expected_folder_name=${encoded}`,
    "/api/packages", `/api/packages/${encoded}`,
  ]);
  expect(JSON.parse(String(fetcher.mock.calls[1][1].body))).toEqual({ expected_folder_name: folder, selections });
  expect(JSON.parse(String(fetcher.mock.calls[2][1].body))).toEqual({ expected_folder_name: folder, order: ["b", "a"] });
  expect(fetcher.mock.calls[1][1].headers).toHaveProperty("If-Match", '"12:7"');
  expect(fetcher.mock.calls.every(call => call[1].credentials === "same-origin" && call[1].cache === "no-store")).toBe(true);
});
