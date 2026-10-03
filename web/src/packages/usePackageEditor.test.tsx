import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { deferred, editorServer, packageSnapshot } from "./testFixtures";
import { usePackageEditor } from "./usePackageEditor";

beforeEach(() => { vi.restoreAllMocks(); Object.defineProperty(navigator, "onLine", { value: true, configurable: true }); });
const wrapper = ({ children }: { children: ReactNode }) => <SessionProvider>{children}</SessionProvider>;
async function setup() {
  const server = editorServer(); vi.stubGlobal("fetch", server.fetcher);
  const hook = renderHook(() => usePackageEditor(), { wrapper });
  await waitFor(() => expect(hook.result.current.snapshot).not.toBeNull());
  return { server, ...hook };
}

it("saves all active video drafts together and omits whole-video keys", async () => {
  const { server, result } = await setup();
  act(() => {
    result.current.setRanges("a", [{ start: 0, end: 5 }, { start: 10, end: 15 }]);
    result.current.setRanges("b", [{ start: 24, end: 30 }]);
  });
  await act(async () => expect(await result.current.save()).toBe(true));
  expect(server.writes[0].body).toEqual({ expected_folder_name: "02-10-2026 13-00", selections: {
    a: [{ start: 0, end: 5 }, { start: 10, end: 15 }], b: [{ start: 24, end: 30 }],
  } });
  expect(result.current.dirty).toBe(false);
  act(() => result.current.setRanges("a", []));
  await act(async () => expect(await result.current.save()).toBe(true));
  expect(server.writes[1].body).toEqual({ expected_folder_name: "02-10-2026 13-00", selections: { b: [{ start: 24, end: 30 }] } });
});

it("uncertain save retains drafts and blocks automatic or manual repeats until explicit refresh", async () => {
  const { server, result } = await setup(); server.writeStatus = 0;
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await act(async () => expect(await result.current.save()).toBe(false));
  expect(result.current.dirty).toBe(true); expect(result.current.stale).toBe(true);
  expect(result.current.error).toBe("uncertain");
  await act(async () => expect(await result.current.save()).toBe(false));
  expect(server.writes).toHaveLength(1);
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.dirty).toBe(true); expect(result.current.stale).toBe(true);
  await act(async () => { await result.current.refresh(); });
  expect(result.current.stale).toBe(false);
});

it("unrelated refresh preserves drafts but authoritative section changes lock them", async () => {
  const { server, result } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  server.snapshot = { ...server.snapshot, render_stale: true };
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.snapshot?.render_stale).toBe(true));
  expect(result.current.draft.a).toEqual([{ start: 0, end: 5 }]); expect(result.current.stale).toBe(false);
  server.snapshot.montage.selections = { a: [{ start: 10, end: 15 }] };
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.stale).toBe(true));
  await act(async () => expect(await result.current.save()).toBe(false));
  expect(server.writes).toHaveLength(0);
  act(() => result.current.discard());
  expect(result.current.draft.a).toEqual([{ start: 10, end: 15 }]); expect(result.current.dirty).toBe(false);
});

it("partial numeric input stays dirty and invalid instead of saving old valid values", async () => {
  const { server, result } = await setup();
  act(() => { result.current.setRanges("a", [{ start: 0, end: 5 }]); result.current.setInput("a", 0, "end", ""); });
  expect(result.current.draftInputs.a[0].end).toBe("");
  expect(result.current.validationErrors.a).toBeTruthy();
  await act(async () => expect(await result.current.save()).toBe(false));
  expect(server.writes).toHaveLength(0);
});

it("dirty video removal requires a decision and discarding it preserves other drafts", async () => {
  const { server, result } = await setup();
  act(() => { result.current.setRanges("a", [{ start: 0, end: 5 }]); result.current.setRanges("b", [{ start: 10, end: 15 }]); });
  await act(async () => expect(await result.current.remove("a")).toBe(false));
  expect(server.writes).toHaveLength(0);
  act(() => result.current.discard("a"));
  await act(async () => expect(await result.current.remove("a")).toBe(true));
  expect(result.current.draft.b).toEqual([{ start: 10, end: 15 }]); expect(result.current.dirty).toBe(true);
});

it("authorization loss clears drafts and invalidates session", async () => {
  const { server, result } = await setup(); server.writeStatus = 401;
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await act(async () => expect(await result.current.save()).toBe(false));
  expect(result.current.snapshot).toBeNull(); expect(result.current.draft).toEqual({});
});

it("later package response wins and aborted old read never overwrites it", async () => {
  const { server, result } = await setup();
  const old = deferred<Response>(); server.pendingRead = old.promise;
  let first!: Promise<void>;
  act(() => { first = result.current.refresh(); });
  server.snapshot = { ...packageSnapshot(), package: { ...packageSnapshot().package, id: 2, folder_name: "new" } };
  await act(async () => { await result.current.refresh(); });
  await act(async () => { old.resolve(server.json(packageSnapshot())); await first; });
  expect(result.current.snapshot?.package.folder_name).toBe("new");
});

it("ordinary read failure keeps readable state and offline blocks writes", async () => {
  const { server, result } = await setup();
  server.pendingRead = Promise.resolve(server.json({}, 500));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.snapshot?.package.folder_name).toBe("02-10-2026 13-00");
  act(() => { Object.defineProperty(navigator, "onLine", { value: false, configurable: true }); window.dispatchEvent(new Event("offline")); result.current.setRanges("a", [{ start: 0, end: 5 }]); });
  await act(async () => expect(await result.current.save()).toBe(false));
  expect(server.writes).toHaveLength(0);
});

it("rollover retains old draft visibly but never applies it to the new package", async () => {
  const { server, result } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  server.snapshot = { ...packageSnapshot(), package: { ...packageSnapshot().package, id: 2, folder_name: "new" } };
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(result.current.snapshot?.package.folder_name).toBe("new"));
  expect(result.current.stale).toBe(true);
  await act(async () => { await result.current.refresh(); expect(await result.current.save()).toBe(false); });
  expect(server.writes).toHaveLength(0);
  act(() => result.current.discard());
  expect(result.current.dirty).toBe(false); expect(result.current.stale).toBe(false);
});

it("unmount aborts in-flight reads and writes without accepting later responses", async () => {
  const { server, result, unmount } = await setup();
  const pending = deferred<Response>(); let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/selections")) { signal = init.signal as AbortSignal; return pending.promise; }
    return server.fetcher(url, init);
  });
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  let save!: Promise<boolean>; act(() => { save = result.current.save(); });
  unmount(); expect(signal?.aborted).toBe(true);
  pending.resolve(server.json({})); expect(await save).toBe(false);
});
