import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { live } from "./live";
import { SessionProvider } from "./session";
import { client } from "./test/fixtures";
import { useLiveData } from "./useLiveData";

const wrapper = ({ children }: { children: ReactNode }) => <SessionProvider>{children}</SessionProvider>;
beforeEach(() => {
  live.stop(); live.acceptMessage("ready", { protocol: 1 });
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(client)));
});
afterEach(() => live.stop());

it("failed required view stays unsynchronized without a timer retry", async () => {
  const load = vi.fn(async () => { throw new Error("read failed"); });
  const hook = renderHook(() => useLiveData(load, true, ["dashboard"]), { wrapper });
  await waitFor(() => expect(hook.result.current.error).toBe(true));
  expect(live.getSnapshot()).toBe("sync-failed");
  expect(load).toHaveBeenCalledTimes(1);
});

it("invalidations refresh only affected active consumers", async () => {
  const dashboard = vi.fn(async () => "dashboard"), activity = vi.fn(async () => "activity");
  renderHook(() => useLiveData(dashboard, true, ["dashboard"]), { wrapper });
  renderHook(() => useLiveData(activity, true, ["activity"]), { wrapper });
  await waitFor(() => expect(activity).toHaveBeenCalledTimes(1));
  await act(async () => live.acceptMessage("change", { event_id: "e1", versions: { dashboard: 1 } }));
  await waitFor(() => expect(dashboard).toHaveBeenCalledTimes(2));
  expect(activity).toHaveBeenCalledTimes(1);
});

it("manual refresh shares the active read instead of aborting and replacing it", async () => {
  let finish!: (value: string) => void;
  let signal!: AbortSignal;
  const load = vi.fn((current: AbortSignal) => {
    signal = current;
    return new Promise<string>(resolve => { finish = resolve; });
  });
  const hook = renderHook(() => useLiveData(load, true, ["dashboard"]), { wrapper });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  const firstSignal = signal;
  act(() => hook.result.current.retry());
  expect(firstSignal.aborted).toBe(false);
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => finish("current"));
  // One deferred verification is allowed, never concurrent/replacement reads.
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  await act(async () => finish("latest"));
  expect(hook.result.current.data).toBe("latest");
});
