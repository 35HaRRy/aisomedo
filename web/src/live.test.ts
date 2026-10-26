import { afterEach, expect, it, vi } from "vitest";
import { LiveCoordinator, readSse } from "./live";

const encoder = new TextEncoder();
function fixture() {
  let output!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(controller) { output = controller; } });
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    init.signal?.addEventListener("abort", () => { try { output.error(new DOMException("", "AbortError")); } catch {} });
    return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
  });
  const live = new LiveCoordinator(fetcher);
  const stop = live.start();
  const frame = (event: string, data: unknown) => output.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
  return { live, fetcher, frame, stop, output };
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("idleHeartbeatDoesNotReadData", async () => {
  vi.useFakeTimers();
  const f = fixture(), read = vi.fn(async () => {});
  const unsubscribe = f.live.subscribe(read, ["dashboard"]);
  await vi.advanceTimersByTimeAsync(0);
  expect(read).not.toHaveBeenCalled();
  f.frame("ready", { protocol: 1 });
  await vi.advanceTimersByTimeAsync(0);
  expect(f.live.getSnapshot()).toBe("live");
  for (let i = 0; i < 40; i++) {
    f.frame("heartbeat", {});
    await vi.advanceTimersByTimeAsync(15000);
  }
  expect(read).toHaveBeenCalledTimes(1);
  expect(f.fetcher).toHaveBeenCalledTimes(1);
  unsubscribe(); f.stop();
});

it("invalidationDuringReadRunsOneFollowup", async () => {
  vi.useFakeTimers();
  const f = fixture();
  let finish!: () => void, active = 0, maximum = 0;
  const read = vi.fn(async () => {
    maximum = Math.max(maximum, ++active);
    await new Promise<void>(resolve => { finish = resolve; }); active--;
  });
  const unsubscribe = f.live.subscribe(read, ["dashboard"]);
  f.frame("ready", { protocol: 1 });
  await vi.advanceTimersByTimeAsync(0);
  for (let i = 1; i <= 8; i++) f.frame("change", { event_id: `e${i}`, versions: { dashboard: i } });
  await vi.advanceTimersByTimeAsync(0);
  finish(); await vi.advanceTimersByTimeAsync(0);
  expect(read).toHaveBeenCalledTimes(2); expect(maximum).toBe(1);
  finish(); await vi.advanceTimersByTimeAsync(0);
  expect(f.live.getSnapshot()).toBe("live");
  f.frame("change", { event_id: "old", versions: { dashboard: 1 } });
  await vi.advanceTimersByTimeAsync(0);
  expect(read).toHaveBeenCalledTimes(2);
  unsubscribe(); f.stop();
});

it("heartbeatDeadlineLocksAt45Seconds", async () => {
  vi.useFakeTimers();
  const f = fixture(), unsubscribe = f.live.subscribe(async () => {}, ["dashboard"]);
  f.frame("ready", { protocol: 1 }); await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(44999); expect(f.live.getSnapshot()).toBe("live");
  await vi.advanceTimersByTimeAsync(2); expect(f.live.getSnapshot()).toBe("disconnected");
  unsubscribe(); f.stop();
});

it("failedRequiredReadStaysLockedWithoutTimerRetries", async () => {
  vi.useFakeTimers();
  const f = fixture(), read = vi.fn(async () => { throw new Error("failed snapshot"); });
  const unsubscribe = f.live.subscribe(read, ["dashboard"]);
  f.frame("ready", { protocol: 1 }); await vi.advanceTimersByTimeAsync(0);
  f.frame("heartbeat", {}); await vi.advanceTimersByTimeAsync(15000);
  expect(f.live.getSnapshot()).toBe("sync-failed"); expect(read).toHaveBeenCalledTimes(1);
  unsubscribe(); f.stop();
});

it("focusWhileLiveDoesNotReadOrCreateAnotherStream", async () => {
  vi.useFakeTimers();
  const f = fixture(), read = vi.fn(async () => {});
  const unsubscribe = f.live.subscribe(read, ["dashboard"]);
  f.frame("ready", { protocol: 1 }); await vi.advanceTimersByTimeAsync(0);
  window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("online"));
  await vi.advanceTimersByTimeAsync(0);
  expect(read).toHaveBeenCalledTimes(1); expect(f.fetcher).toHaveBeenCalledTimes(1);
  unsubscribe(); f.stop();
});

it("unknown event types do not prevent a later valid readiness frame", async () => {
  vi.useFakeTimers();
  const f = fixture(), read = vi.fn(async () => {});
  const unsubscribe = f.live.subscribe(read, ["dashboard"]);
  f.output.enqueue(encoder.encode("event: future-version\ndata: opaque-not-json\n\n"));
  f.frame("ready", { protocol: 1 }); await vi.advanceTimersByTimeAsync(0);
  expect(f.live.getSnapshot()).toBe("live"); expect(read).toHaveBeenCalledTimes(1);
  unsubscribe(); f.stop();
});

it.each([
  ["ready", { protocol: 2 }],
  ["change", { event_id: "e", versions: { dashboard: "1" } }],
])("malformed required protocol data locks the view", async (event, data) => {
  vi.useFakeTimers();
  const f = fixture(), read = vi.fn(async () => {});
  const unsubscribe = f.live.subscribe(read, ["dashboard"]);
  f.frame(String(event), data); await vi.advanceTimersByTimeAsync(0);
  expect(f.live.getSnapshot()).toBe("disconnected"); expect(read).not.toHaveBeenCalled();
  unsubscribe(); f.stop();
});

it("wrong content type never unlocks or starts required reads", async () => {
  vi.useFakeTimers();
  const live = new LiveCoordinator(async () => new Response("{}", { headers: { "Content-Type": "application/json" } }));
  const read = vi.fn(async () => {}), unsubscribe = live.subscribe(read, ["dashboard"]), stop = live.start();
  await vi.advanceTimersByTimeAsync(0);
  expect(live.getSnapshot()).toBe("disconnected"); expect(read).not.toHaveBeenCalled();
  unsubscribe(); stop();
});

it("foreground recovery subscribes again before reloading and ignores redundant focus", async () => {
  vi.useFakeTimers();
  let hidden = false;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  const f = fixture(), read = vi.fn(async () => {}), unsubscribe = f.live.subscribe(read, ["dashboard"]);
  f.frame("ready", { protocol: 1 }); await vi.advanceTimersByTimeAsync(0);
  hidden = true; document.dispatchEvent(new Event("visibilitychange"));
  expect(f.live.getSnapshot()).toBe("disconnected");
  let output!: ReadableStreamDefaultController<Uint8Array>;
  f.fetcher.mockImplementation(async () => new Response(new ReadableStream({ start(controller) { output = controller; } }), { headers: { "Content-Type": "text/event-stream" } }));
  hidden = false; document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(0); expect(read).toHaveBeenCalledTimes(1);
  output.enqueue(encoder.encode('event: ready\ndata: {"protocol":1}\n\n'));
  await vi.advanceTimersByTimeAsync(0);
  expect(read).toHaveBeenCalledTimes(2); expect(f.fetcher).toHaveBeenCalledTimes(2);
  window.dispatchEvent(new Event("focus")); await vi.advanceTimersByTimeAsync(0);
  expect(read).toHaveBeenCalledTimes(2);
  unsubscribe(); f.stop();
});

it("streamFramesSurviveUtf8AndCrLfSplits", async () => {
  const bytes = encoder.encode('event: ready\r\ndata: {\r\ndata: "protocol": 1, "text": "ö"}\r\n\r\n');
  const body = new ReadableStream<Uint8Array>({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close();
  } });
  const frames: unknown[] = [];
  await readSse(body, (event, data) => frames.push({ event, data }), new AbortController().signal);
  expect(frames).toEqual([{ event: "ready", data: { protocol: 1, text: "ö" } }]);
});

it.each(["data: {}\n", `data: ${"x".repeat(65537)}\n\n`, `${":x\r\n".repeat(20000)}data: {}\r\n\r\n`])("rejectsIncompleteOrOversizedFrames", async text => {
  const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(encoder.encode(text)); controller.close(); } });
  await expect(readSse(body, () => {}, new AbortController().signal)).rejects.toThrow();
});

it.each([401, 426])("HTTP %i cannot unlock editing or retry state reads", async status => {
  vi.useFakeTimers();
  const fetcher = vi.fn(async () => new Response("", { status }));
  const live = new LiveCoordinator(fetcher), read = vi.fn(async () => {});
  const unsubscribe = live.subscribe(read, ["dashboard"]), stop = live.start();
  await vi.advanceTimersByTimeAsync(120000);
  expect(live.getSnapshot()).toBe(status === 401 ? "unauthorized" : "disconnected");
  expect(read).not.toHaveBeenCalled(); expect(fetcher).toHaveBeenCalledTimes(1);
  unsubscribe(); stop();
});
