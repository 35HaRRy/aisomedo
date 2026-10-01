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
