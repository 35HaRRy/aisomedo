import { afterEach, expect, it, vi } from "vitest";
import { api, request } from "./client";

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

it.each(["private body", '{"detail":[{"input":"secret"}]}', "{"])("ignores unstructured error body %s", async body => {
  vi.stubGlobal("fetch", async () => new Response(body, { status: 422 }));
  await expect(request("/api/media/uploads")).rejects.toMatchObject({ status: 422, detail: undefined });
});
