import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { SessionProvider } from "../session";
import { invalidateLive } from "../test/live";
import { live } from "../live";
import { readDraft, writeDraft } from "./drafts";
import * as drafts from "./drafts";
import { draftMemory } from "../test/drafts";
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

it("pauses hidden editor reads without resetting drafts and reconciles on return", async () => {
  const server = editorServer(), fetcher = vi.fn(server.fetcher); vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(({ enabled }) => usePackageEditor(enabled), { initialProps: { enabled: true }, wrapper });
  await waitFor(() => expect(hook.result.current.canEdit).toBe(true));
  act(() => hook.result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await waitFor(() => expect(hook.result.current.persisting).toBe(false));
  hook.rerender({ enabled: false });
  const reads = () => fetcher.mock.calls.filter(([url]) => url.endsWith("/editor")).length;
  const before = reads();
  server.snapshot.montage.selections.a = [{ start: 2, end: 8 }];
  await act(async () => invalidateLive());
  expect(reads()).toBe(before);
  expect(hook.result.current.draftInputs.a[0].end).toBe("5");
  expect(hook.result.current.canEdit).toBe(false);
  expect(hook.result.current.stale).toBe(true);
  act(() => hook.result.current.setInput("a", 0, "end", "9"));
  expect(hook.result.current.draftInputs.a[0].end).toBe("5");
  await act(async () => expect(await hook.result.current.save("a")).toBe(false));
  hook.rerender({ enabled: true });
  await waitFor(() => expect(hook.result.current.conflicts).toHaveProperty("video:a"));
  expect(reads()).toBe(before + 1);
  expect(hook.result.current.draftInputs.a[0].end).toBe("5");
});

it("leaving during draft restoration cancels the deferred editor read", async () => {
  const pending = deferred<Awaited<ReturnType<typeof drafts.listDrafts>>>();
  const restore = vi.spyOn(drafts, "listDrafts").mockReturnValueOnce(pending.promise);
  const server = editorServer(), fetcher = vi.fn(server.fetcher); vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(({ enabled }) => usePackageEditor(enabled), { initialProps: { enabled: true }, wrapper });
  await waitFor(() => expect(restore).toHaveBeenCalledTimes(1));
  hook.rerender({ enabled: false });
  await act(async () => pending.resolve([]));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/editor"))).toHaveLength(0);
  expect(hook.result.current.snapshot).toBeNull();
  hook.rerender({ enabled: true });
  await waitFor(() => expect(hook.result.current.canEdit).toBe(true));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/editor"))).toHaveLength(1);
});

it("restores incomplete durable input read-only before reconnect synchronization", async () => {
  const { server, result, unmount } = await setup();
  act(() => { result.current.setRanges("a", [{ start: 0, end: 5 }]); result.current.setInput("a", 0, "end", ""); });
  const key = { origin: window.location.origin, clientId: 1, packageId: 1 };
  await waitFor(async () => expect((await readDraft(key))?.inputs.a[0].end).toBe(""));
  unmount(); live.stop();
  vi.stubGlobal("fetch", server.fetcher);
  const reopened = renderHook(() => usePackageEditor(), { wrapper });
  await waitFor(() => expect(reopened.result.current.draftInputs.a?.[0].end).toBe(""));
  expect(reopened.result.current.canEdit).toBe(false);
  await act(async () => live.acceptMessage("ready", { protocol: 1 }));
  await waitFor(() => expect(reopened.result.current.canEdit).toBe(true));
  expect(reopened.result.current.validationErrors.a).toBeTruthy();
  expect(server.writes).toHaveLength(0);
});

it("independent media changes merge while same-group conflicts require a new baseline", async () => {
  const { server, result } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  server.snapshot.montage.selections.b = [{ start: 10, end: 15 }];
  await act(async () => invalidateLive());
  await waitFor(() => expect(result.current.snapshot?.montage.selections.b).toEqual([{ start: 10, end: 15 }]));
  expect(result.current.stale).toBe(false);
  server.snapshot.montage.selections.a = [{ start: 2, end: 8 }];
  await act(async () => invalidateLive());
  await waitFor(() => expect(result.current.conflicts).toHaveProperty("video:a"));
  expect(result.current.canSave).toBe(false);
  await act(async () => result.current.resolveConflict("video:a", "local"));
  await waitFor(() => expect(result.current.canSave).toBe(true));
  const persisted = await readDraft({ origin: window.location.origin, clientId: 1, packageId: 1 });
  expect(persisted?.groups["video:a"].base).toEqual({ ranges: [{ start: 2, end: 8 }] });
  expect(result.current.draft.a).toEqual([{ start: 0, end: 5 }]);
});

it("failed draft persistence is visible and never sends an unprotected command", async () => {
  const { server, result } = await setup();
  draftMemory.failWrites();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await waitFor(() => expect(result.current.persistenceError).toBe("unavailable"));
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(result.current.draft.a).toEqual([{ start: 0, end: 5 }]);
  expect(server.writes).toHaveLength(0);
});

it("a competing tab cannot be overwritten by a later local keystroke", async () => {
  const { result } = await setup();
  const key = { origin: window.location.origin, clientId: 1, packageId: 1 };
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await waitFor(async () => expect(await readDraft(key)).not.toBeNull());
  const remote = (await readDraft(key))!; remote.inputs.a[0].end = "9";
  await writeDraft(key, remote.localRevision, remote);
  act(() => result.current.setInput("a", 0, "end", "7"));
  await waitFor(() => expect(result.current.persistenceError).toBe("conflict"));
  expect((await readDraft(key))?.inputs.a[0].end).toBe("9");
  expect(result.current.draftInputs.a[0].end).toBe("7");
});

it("reopening a lost committed save reconciles without resubmitting", async () => {
  const { server, result, unmount } = await setup();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    const response = await server.fetcher(url, init);
    if (url.endsWith("/edits")) throw new TypeError("lost acknowledgement");
    return response;
  });
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect((await readDraft({ origin: window.location.origin, clientId: 1, packageId: 1 }))?.uncertain).toBe(true);
  unmount(); vi.stubGlobal("fetch", server.fetcher);
  const reopened = renderHook(() => usePackageEditor(), { wrapper });
  await waitFor(() => expect(reopened.result.current.snapshot?.montage.selections.a).toHaveLength(1));
  await waitFor(() => expect(reopened.result.current.dirty).toBe(false));
  expect(reopened.result.current.stale).toBe(false);
  expect(server.writes).toHaveLength(1);
  expect(await readDraft({ origin: window.location.origin, clientId: 1, packageId: 1 })).toBeNull();
});

it("direct editor handlers cannot change inputs or submit while disconnected", async () => {
  const { server, result } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  const before = structuredClone(result.current.draftInputs);
  act(() => live.stop());
  act(() => { result.current.setInput("a", 0, "end", "8"); result.current.setRanges("b", [{ start: 1, end: 2 }]); result.current.discard(); });
  await act(async () => {
    expect(await result.current.save("a")).toBe(false);
    expect(await result.current.remove("b")).toBe(false);
    expect(await result.current.restore("b")).toBe(false);
    expect(await result.current.reorder(["b", "a"])).toBe(false);
    expect(await result.current.renderPreview()).toBe(false);
    expect(await result.current.clearPackage()).toBeNull();
  });
  expect(result.current.draftInputs).toEqual(before); expect(server.writes).toHaveLength(0);
});

it("a restored draft for a deleted package remains recoverable without a snapshot", async () => {
  const { result, server, unmount } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await waitFor(() => expect(result.current.persisting).toBe(false));
  unmount();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => url.endsWith("/editor") ? server.json({}, 404) : server.fetcher(url, init));
  const reopened = renderHook(() => usePackageEditor(), { wrapper });
  await waitFor(() => expect(reopened.result.current.draftFolder).toBe("02-10-2026 13-00"));
  expect(reopened.result.current.canEdit).toBe(false);
  expect(reopened.result.current.draftInputs.a[0].end).toBe("5");
});

it.each(["", "Infinity", "100"])("saves A independently while B contains %s and retains B after reopening", async end => {
  const { server, result, unmount } = await setup();
  act(() => {
    result.current.setRanges("a", [{ start: 0, end: 5 }]);
    result.current.setRanges("b", [{ start: 10, end: 15 }]);
    result.current.setInput("b", 0, "end", end);
  });
  await act(async () => expect(await result.current.save("a")).toBe(true));
  expect(server.writes[0].body).toMatchObject({ changes: [
    { key: "video:a", base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 5 }] } },
  ] });
  expect(result.current.isDirty("a")).toBe(false);
  expect(result.current.draftInputs.b).toEqual([{ start: "10", end }]);
  unmount();
  const reopened = renderHook(() => usePackageEditor(), { wrapper });
  await waitFor(() => expect(reopened.result.current.snapshot).not.toBeNull());
  expect(reopened.result.current.draftInputs.b).toEqual([{ start: "10", end }]);
  act(() => reopened.result.current.discard("a"));
  expect(reopened.result.current.draftInputs.b).toEqual([{ start: "10", end }]);
});

it("confirmed removal discards only acknowledged target, never failed requests", async () => {
  const { server, result } = await setup();
  act(() => {
    result.current.setRanges("a", [{ start: 0, end: 5 }]);
    result.current.setRanges("b", [{ start: 10, end: 15 }]);
  });
  server.writeStatus = 422;
  await act(async () => expect(await result.current.remove("a", true)).toBe(false));
  expect(result.current.isDirty("a")).toBe(true);
  expect(result.current.isDirty("b")).toBe(true);
  server.writeStatus = 200;
  await act(async () => expect(await result.current.remove("a", true)).toBe(true));
  expect(result.current.isDirty("a")).toBe(false);
  expect(result.current.draftInputs.b).toEqual([{ start: "10", end: "15" }]);
  expect(result.current.stale).toBe(false);
});

it("photo save ignores another card's over-limit draft but checks persisted total", async () => {
  const { server, result } = await setup();
  server.snapshot.media[1] = { ...server.snapshot.media[1], is_video: false, source_duration: null, effective_duration: 3 };
  server.snapshot.montage.max_duration_seconds = 40;
  await act(async () => { await result.current.refresh(); });
  act(() => {
    result.current.setRanges("a", [{ start: 0, end: 30 }]);
    result.current.setPhotoDuration("b", "20");
  });
  expect(result.current.canSaveMedia("a")).toBe(true);
  expect(result.current.saveBlockedReasonFor("b")).toBe("limit");
  act(() => result.current.setPhotoDuration("b", "4"));
  await act(async () => expect(await result.current.save("b")).toBe(true));
  expect(server.writes[0].body).toMatchObject({ changes: [
    { key: "photo:b", base: { seconds: 3 }, proposed: { seconds: 4 } },
  ] });
  expect(result.current.isDirty("a")).toBe(true);
});

it("retry uses saved generation without submitting drafts and refreshes a stale retry", async () => {
  const { server, result } = await setup();
  server.snapshot.media[0].section_preview = { status: "failed", generation: "failed-a", url: null, duration: null };
  await act(async () => { await result.current.refresh(); });
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/sections/retry")) {
      await server.fetcher(url, init);
      return server.json({ ...server.snapshot, media: server.snapshot.media.map(m => m.media_id === "a"
        ? { ...m, section_preview: { status: "queued", generation: "replacement", url: null, duration: null } } : m) });
    }
    return server.fetcher(url, init);
  });
  await act(async () => expect(await result.current.retrySectionPreview("a")).toBe(true));
  expect(server.writes[0].body).toEqual({ expected_package_id: 1,
    expected_folder_name: "02-10-2026 13-00", expected_generation: "failed-a" });
  expect(result.current.draftInputs.a).toEqual([{ start: "0", end: "5" }]);
  vi.stubGlobal("fetch", server.fetcher);
  server.writeStatus = 409;
  await act(async () => expect(await result.current.retrySectionPreview("a")).toBe(false));
  expect(result.current.stale).toBe(false);
  expect(server.writes).toHaveLength(2);
});

it("saves only chosen group, including whole-video selection", async () => {
  const { server, result } = await setup();
  act(() => {
    result.current.setRanges("a", [{ start: 0, end: 5 }, { start: 10, end: 15 }]);
    result.current.setRanges("b", [{ start: 24, end: 30 }]);
  });
  await act(async () => expect(await result.current.save("a")).toBe(true));
  expect(server.writes[0].body).toEqual({ expected_folder_name: "02-10-2026 13-00", expected_package_id: 1, base_content_revision: 1,
    changes: [{ key: "video:a", base: { ranges: [] }, proposed: { ranges: [{ start: 0, end: 5 }, { start: 10, end: 15 }] } }] });
  expect(result.current.isDirty("a")).toBe(false);
  expect(result.current.isDirty("b")).toBe(true);
  act(() => result.current.setRanges("a", []));
  await act(async () => expect(await result.current.save("a")).toBe(true));
  expect(server.writes[1].body).toEqual({ expected_folder_name: "02-10-2026 13-00", expected_package_id: 1, base_content_revision: 1,
    changes: [{ key: "video:a", base: { ranges: [{ start: 0, end: 5 }, { start: 10, end: 15 }] }, proposed: { ranges: [] } }] });
});

it("uncertain save retains drafts and blocks automatic or manual repeats until explicit refresh", async () => {
  const { server, result } = await setup(); server.writeStatus = 0;
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(result.current.dirty).toBe(true); expect(result.current.stale).toBe(true);
  expect(result.current.error).toBe("uncertain");
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(server.writes).toHaveLength(1);
  act(() => invalidateLive());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.dirty).toBe(true); expect(result.current.stale).toBe(true);
  await act(async () => { await result.current.refresh(); });
  expect(result.current.stale).toBe(false);
});

it("unrelated refresh preserves drafts but authoritative section changes lock them", async () => {
  const { server, result } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  server.snapshot = { ...server.snapshot, render_stale: true };
  act(() => invalidateLive());
  await waitFor(() => expect(result.current.snapshot?.render_stale).toBe(true));
  expect(result.current.draft.a).toEqual([{ start: 0, end: 5 }]); expect(result.current.stale).toBe(false);
  server.snapshot.montage.selections = { a: [{ start: 10, end: 15 }] };
  act(() => invalidateLive());
  await waitFor(() => expect(result.current.stale).toBe(true));
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(server.writes).toHaveLength(0);
  act(() => result.current.discard());
  expect(result.current.draft.a).toEqual([{ start: 10, end: 15 }]); expect(result.current.dirty).toBe(false);
});

it("partial numeric input stays dirty and invalid instead of saving old valid values", async () => {
  const { server, result } = await setup();
  act(() => { result.current.setRanges("a", [{ start: 0, end: 5 }]); result.current.setInput("a", 0, "end", ""); });
  expect(result.current.draftInputs.a[0].end).toBe("");
  expect(result.current.validationErrors.a).toBeTruthy();
  await act(async () => expect(await result.current.save("a")).toBe(false));
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
  await act(async () => expect(await result.current.save("a")).toBe(false));
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
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(server.writes).toHaveLength(0);
});

it("rollover retains old draft visibly but never applies it to the new package", async () => {
  const { server, result } = await setup();
  const oldKey = { origin: window.location.origin, clientId: 1, packageId: 1 };
  const newKey = { ...oldKey, packageId: 2 };
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await waitFor(async () => expect(await readDraft(oldKey)).not.toBeNull());
  server.snapshot = { ...packageSnapshot(), package: { ...packageSnapshot().package, id: 2, folder_name: "new" } };
  act(() => invalidateLive());
  await waitFor(() => expect(result.current.snapshot?.package.folder_name).toBe("new"));
  expect(result.current.stale).toBe(true);
  await act(async () => { await result.current.refresh(); expect(await result.current.save("a")).toBe(false); });
  expect(server.writes).toHaveLength(0);
  act(() => result.current.discard());
  await waitFor(async () => expect(await readDraft(oldKey)).toBeNull());
  expect(result.current.dirty).toBe(false); expect(result.current.stale).toBe(false);
  act(() => result.current.setRanges("a", [{ start: 1, end: 2 }]));
  await waitFor(async () => expect((await readDraft(newKey))?.inputs.a[0].end).toBe("2"));
  expect(server.writes).toHaveLength(0);
});

it("unmount aborts in-flight reads and writes without accepting later responses", async () => {
  const { server, result, unmount } = await setup();
  const pending = deferred<Response>(); let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    if (url.endsWith("/edits")) { signal = init.signal as AbortSignal; return pending.promise; }
    return server.fetcher(url, init);
  });
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  let save!: Promise<boolean>; act(() => { save = result.current.save("a"); });
  await waitFor(() => expect(signal).toBeDefined());
  unmount(); expect(signal?.aborted).toBe(true);
  pending.resolve(server.json({})); expect(await save).toBe(false);
});

it.each(["reorder", "remove", "restore"] as const)("%s acknowledgement cannot rebase unrelated saved sections over dirty drafts", async operation => {
  const { server, result } = await setup();
  if (operation === "restore") {
    await act(async () => { await result.current.remove("b"); });
  }
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  server.snapshot.montage.selections.a = [{ start: 10, end: 15 }];
  await act(async () => {
    if (operation === "reorder") await result.current.reorder(["b", "a"]);
    else await result.current[operation]("b");
  });
  expect(result.current.draft.a).toEqual([{ start: 0, end: 5 }]);
  expect(result.current.stale).toBe(true); expect(result.current.canSave).toBe(false);
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(server.snapshot.montage.selections.a).toEqual([{ start: 10, end: 15 }]);
});

it("discard after lost committed save still requires explicit authoritative refresh", async () => {
  const { server, result } = await setup();
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    const response = await server.fetcher(url, init);
    if (url.endsWith("/edits")) throw new TypeError("acknowledgement lost after commit");
    return response;
  });
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await act(async () => expect(await result.current.save("a")).toBe(false));
  expect(server.snapshot.montage.selections.a).toEqual([{ start: 0, end: 5 }]);
  act(() => result.current.discard());
  expect(result.current.dirty).toBe(false); expect(result.current.stale).toBe(true);
  expect(result.current.error).toBe("uncertain");
  await act(async () => expect(await result.current.reorder(["b", "a"])).toBe(false));
  act(() => invalidateLive());
  await waitFor(() => expect(result.current.snapshot?.montage.selections.a).toHaveLength(1));
  expect(result.current.stale).toBe(true);
  vi.stubGlobal("fetch", server.fetcher);
  await act(async () => { await result.current.refresh(); });
  expect(result.current.stale).toBe(false);
  act(() => result.current.setRanges("b", [{ start: 10, end: 15 }]));
  await act(async () => expect(await result.current.save("b")).toBe(true));
  expect(server.snapshot.montage.selections).toEqual({ a: [{ start: 0, end: 5 }], b: [{ start: 10, end: 15 }] });
});

it("photo drafts count, validate, save and discard without editing source files", async () => {
  const { server, result } = await setup();
  server.snapshot.media[1] = { ...server.snapshot.media[1], filename: "photo.jpg", is_video: false, source_duration: null, effective_duration: 3 };
  await act(async () => { await result.current.refresh(); });
  act(() => result.current.setPhotoDuration("b", "4.5"));
  expect(result.current.proposedTotal).toBe(34.5);
  expect(result.current.canSave).toBe(true);
  await act(async () => expect(await result.current.save("b")).toBe(true));
  expect(server.writes[0].body).toEqual({ expected_folder_name: "02-10-2026 13-00", expected_package_id: 1, base_content_revision: 1,
    changes: [{ key: "photo:b", base: { seconds: 3 }, proposed: { seconds: 4.5 } }] });
  expect(result.current.dirty).toBe(false);
  act(() => result.current.setPhotoDuration("b", ""));
  expect(result.current.canSave).toBe(false); expect(result.current.saveBlockedReason).toBe("invalid");
  act(() => result.current.discard());
  expect(result.current.draftInputs.b[0].end).toBe("4.5");
});

it("render-stale message never blocks valid draft save; discard leaves saved server state untouched", async () => {
  const { server, result } = await setup();
  server.snapshot.render_stale = true;
  await act(async () => { await result.current.refresh(); });
  expect(result.current.saveBlockedReason).toBe("unchanged");
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  expect(result.current.canSave).toBe(true); expect(result.current.saveBlockedReason).toBeNull();
  act(() => result.current.discard());
  expect(result.current.dirty).toBe(false); expect(server.writes).toHaveLength(0);
});

it("renders saved montage while retaining unsaved drafts and clears only confirmed package identity", async () => {
  const { server, result } = await setup();
  act(() => result.current.setRanges("a", [{ start: 0, end: 5 }]));
  await act(async () => expect(await result.current.renderPreview()).toBe(true));
  expect(server.writes[0].url).toBe("/api/packages/active/render");
  expect(result.current.dirty).toBe(true); expect(result.current.stale).toBe(false);
  await act(async () => expect(await result.current.clearPackage()).toEqual({ folder_name: "02-10-2026 13-00", upload_ids: ["upload-a"] }));
  expect(server.writes[1].body).toEqual({ expected_folder_name: "02-10-2026 13-00", expected_package_id: 1, confirmed: true });
  expect(result.current.snapshot).toBeNull(); expect(result.current.dirty).toBe(false);
});

it("failed cleanup retains exact retry identity across remount; never substitutes replacement package", async () => {
  localStorage.clear();
  const { server, result, unmount } = await setup();
  server.writeStatus = 503;
  await act(async () => expect(await result.current.clearPackage()).toBeNull());
  expect(result.current.pendingClear).toEqual({ id: 1, folder_name: "02-10-2026 13-00", content_revision: 1 });
  unmount();
  server.snapshot.package = { ...server.snapshot.package, id: 2 };
  const replacement = renderHook(() => usePackageEditor(), { wrapper });
  await waitFor(() => expect(replacement.result.current.pendingClear?.id).toBe(1));
  expect(replacement.result.current.snapshot).toBeNull();
  server.writeStatus = 200;
  await act(async () => expect(await replacement.result.current.clearPackage()).not.toBeNull());
  expect(server.writes[1].body).toMatchObject({ expected_package_id: 1 });
  expect(replacement.result.current.pendingClear).toBeNull();
  localStorage.clear();
});
