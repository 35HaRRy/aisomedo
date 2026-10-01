import { afterEach, expect, it, vi } from "vitest";
import { startLiveRefresh } from "./live";

afterEach(() => vi.useRealTimers());

it("refreshes persisted reviews each five seconds, pauses hidden and resumes", async () => {
  vi.useFakeTimers();
  let remote = "pending";
  let visible = "";
  let hidden = false;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  const stop = startLiveRefresh(async () => { visible = remote; });
  await vi.advanceTimersByTimeAsync(0);
  expect(visible).toBe("pending");
  remote = "resolved";
  await vi.advanceTimersByTimeAsync(4999);
  expect(visible).toBe("pending");
  await vi.advanceTimersByTimeAsync(1);
  expect(visible).toBe("resolved");
  hidden = true;
  document.dispatchEvent(new Event("visibilitychange"));
  remote = "new review";
  await vi.advanceTimersByTimeAsync(10000);
  expect(visible).toBe("resolved");
  hidden = false;
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(0);
  expect(visible).toBe("new review");
  stop();
});

it("never overlaps slow work and cleanup aborts it", async () => {
  vi.useFakeTimers();
  let active = 0;
  let maximum = 0;
  let signal!: AbortSignal;
  const stop = startLiveRefresh(async s => {
    signal = s;
    maximum = Math.max(maximum, ++active);
    await new Promise<void>(resolve => s.addEventListener("abort", () => { active--; resolve(); }));
  });
  await vi.advanceTimersByTimeAsync(20000);
  window.dispatchEvent(new Event("focus"));
  window.dispatchEvent(new Event("online"));
  await vi.advanceTimersByTimeAsync(0);
  expect(maximum).toBe(1);
  stop();
  expect(signal.aborted).toBe(true);
  await vi.advanceTimersByTimeAsync(10000);
  expect(active).toBe(0);
});

it("recovers after failure and coalesces reconnect events", async () => {
  vi.useFakeTimers();
  let attempts = 0;
  let data = "";
  const stop = startLiveRefresh(async () => {
    if (++attempts === 1) throw new Error("offline");
    data = "fresh";
  });
  await vi.advanceTimersByTimeAsync(0);
  expect(data).toBe("");
  window.dispatchEvent(new Event("focus"));
  window.dispatchEvent(new Event("online"));
  await vi.advanceTimersByTimeAsync(0);
  expect(data).toBe("fresh");
  expect(attempts).toBe(2);
  stop();
});
