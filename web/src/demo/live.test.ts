import { afterEach, expect, it, vi } from "vitest";
import { LiveCoordinator } from "../live";
import { transportFetch } from "../api/transport";
import { startDemo, stopDemo } from "./runtime";

afterEach(() => { stopDemo(); vi.useRealTimers(); vi.unstubAllGlobals(); window.location.hash = ""; });
it("reaches live, refreshes local mutations, and stays local beyond the heartbeat deadline", async () => {
  vi.useFakeTimers(); window.location.hash = "#/demo/dashboard";
  const native = vi.fn(); vi.stubGlobal("fetch", native); startDemo();
  const live = new LiveCoordinator(transportFetch); let reads = 0;
  const unsubscribe = live.subscribe(async () => { reads++; await transportFetch("/api/dashboard"); }, ["dashboard"]);
  const stop = live.start();
  await vi.advanceTimersByTimeAsync(1);
  expect(live.getSnapshot()).toBe("live");
  await transportFetch("/api/settings/branding", { method: "PATCH", body: JSON.stringify({ caption_template: "Changed" }) });
  await vi.advanceTimersByTimeAsync(1); expect(reads).toBe(2);
  await vi.advanceTimersByTimeAsync(60000); expect(live.getSnapshot()).toBe("live");
  expect(native).not.toHaveBeenCalled();
  unsubscribe(); stop(); expect(startDemo().state.listeners.size).toBe(0);
});
it("stale owner cleanup cannot disable a restarted live workspace", async () => {
  vi.useFakeTimers(); startDemo();
  const coordinator = new LiveCoordinator(transportFetch);
  const releaseOld = coordinator.start(); await vi.advanceTimersByTimeAsync(1);
  coordinator.stop(); releaseOld();
  const releaseNew = coordinator.start(); await vi.advanceTimersByTimeAsync(1);
  expect(coordinator.getSnapshot()).toBe("live");
  releaseOld(); expect(coordinator.getSnapshot()).toBe("live");
  releaseNew();
});
