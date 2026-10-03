import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ActiveEditorOut, ClearPackageOut } from "../api/openapi";
import { startLiveRefresh } from "../live";
import { useSession } from "../session";
import { proposedDuration, validateRanges, type RangeInput, type SelectionMap, type VideoRange } from "./ranges";

type EditorError = "read" | "uncertain" | "conflict" | "invalid" | "limit" | "render" | "cleanup" | null;
type ClearTarget = { id: number; folder_name: string };
type SaveBlockedReason = "unchanged" | "busy" | "offline" | "refresh" | "invalid" | "duration" | "limit" | null;
interface Data {
  pendingClear: ClearTarget | null;
  snapshot: ActiveEditorOut | null;
  draftInputs: Record<string, RangeInput[]>;
  base: Record<string, RangeInput[]>;
  baseFolder: string | null;
  stale: boolean;
  readRequired: boolean;
  loading: boolean;
  busy: boolean;
  error: EditorError;
}
export interface PackageEditorState {
  pendingClear: ClearTarget | null;
  snapshot: ActiveEditorOut | null;
  draft: SelectionMap;
  draftInputs: Record<string, RangeInput[]>;
  validationErrors: Record<string, string>;
  dirty: boolean;
  stale: boolean;
  offline: boolean;
  loading: boolean;
  busy: boolean;
  error: EditorError;
  proposedTotal: number | null;
  canSave: boolean;
  saveBlockedReason: SaveBlockedReason;
  photoDurations: Record<string, number>;
  isDirty(id: string): boolean;
  setRanges(id: string, ranges: VideoRange[]): void;
  setInput(id: string, index: number, bound: "start" | "end", value: string): void;
  setPhotoDuration(id: string, value: string): void;
  renderPreview(): Promise<boolean>;
  clearPackage(): Promise<ClearPackageOut | null>;
  save(): Promise<boolean>;
  discard(id?: string): void;
  refresh(): Promise<void>;
  reorder(order: string[]): Promise<boolean>;
  remove(id: string): Promise<boolean>;
  restore(id: string): Promise<boolean>;
}
const empty = (): Data => ({ pendingClear: null, snapshot: null, draftInputs: {}, base: {}, baseFolder: null, stale: false, readRequired: false, loading: false, busy: false, error: null });
const clearKey = (clientId: number) => `aisomedo.package-clear.v1:${clientId}`;
function rememberedClear(clientId: number): ClearTarget | null {
  try {
    const value = JSON.parse(localStorage.getItem(clearKey(clientId)) ?? "null");
    return value && Number.isSafeInteger(value.id) && value.id > 0 && typeof value.folder_name === "string" ? value : null;
  } catch { return null; }
}
function rememberClear(clientId: number | undefined, target: ClearTarget | null) {
  if (clientId === undefined) return;
  try { if (target) localStorage.setItem(clearKey(clientId), JSON.stringify(target)); else localStorage.removeItem(clearKey(clientId)); }
  catch { /* Blocked storage does not prevent an in-session cleanup retry. */ }
}
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
function inputs(snapshot: ActiveEditorOut): Record<string, RangeInput[]> {
  return Object.fromEntries(snapshot.media.map(m => [m.media_id,
    m.is_video ? (snapshot.montage.selections[m.media_id] ?? []).map(r => ({ start: String(r.start), end: String(r.end) }))
      : [{ start: "0", end: String(m.effective_duration ?? 3) }],
  ]));
}
const changed = (data: Data, id: string) => !equal(data.draftInputs[id] ?? [], data.base[id] ?? []);
const dirty = (data: Data) => Object.keys(data.draftInputs).some(id => changed(data, id));
function fingerprint(snapshot: ActiveEditorOut | null): string {
  return JSON.stringify(snapshot && { package: snapshot.package.id, folder: snapshot.package.folder_name,
    order: snapshot.montage.order, selections: snapshot.montage.selections,
    cards: snapshot.montage.card_duration, limit: snapshot.montage.max_duration_seconds,
    media: snapshot.media.map(m => [m.media_id, m.status, m.processed, m.effective_duration]),
  });
}
type WriteChange = { kind: "selections"; selections: SelectionMap; photos: Record<string, number> } | { kind: "order"; order: string[] } | { kind: "remove" | "restore"; id: string } | { kind: "render" | "clear" };
function expectedWrite(snapshot: ActiveEditorOut, change: WriteChange): ActiveEditorOut {
  const next = { ...snapshot, montage: { ...snapshot.montage }, media: snapshot.media.map(m => ({ ...m })) };
  if (change.kind === "selections") {
    const removed = Object.fromEntries(Object.entries(snapshot.montage.selections).filter(([id]) => snapshot.media.some(m => m.media_id === id && m.status === "removed")));
    next.montage.selections = { ...removed, ...change.selections };
    next.media.forEach(m => { if (!m.is_video && m.media_id in change.photos) m.effective_duration = change.photos[m.media_id]; });
  } else if (change.kind === "order") next.montage.order = change.order;
  else if (change.kind === "remove" || change.kind === "restore") {
    const media = next.media.find(m => m.media_id === change.id);
    if (media) media.status = change.kind === "remove" ? "removed" : "finalized";
    next.montage.order = snapshot.montage.order.filter(id => id !== change.id);
    if (change.kind === "restore") next.montage.order.splice(media?.removed_position ?? next.montage.order.length, 0, change.id);
  }
  return next;
}
function writeFingerprint(snapshot: ActiveEditorOut): string {
  // Duration is derived from selections/source metadata, not an independent
  // change. Compare the inputs, allowing only this acknowledged operation.
  return fingerprint({ ...snapshot, media: snapshot.media.map(m => ({ ...m, effective_duration: m.is_video ? null : m.effective_duration })) });
}
function numeric(data: Data): { draft: SelectionMap; photoDurations: Record<string, number>; validationErrors: Record<string, string> } {
  const draft: SelectionMap = {}, photoDurations: Record<string, number> = {}, validationErrors: Record<string, string> = {};
  for (const [id, values] of Object.entries(data.draftInputs)) {
    const media = data.snapshot?.media.find(m => m.media_id === id);
    if (!media || media.status !== "finalized") continue;
    if (!media.is_video) {
      const seconds = Number(values[0]?.end);
      if (!values[0]?.end.trim() || !Number.isFinite(seconds) || seconds < 1 / 25) validationErrors[id] = "number";
      else photoDurations[id] = seconds;
      continue;
    }
    const ranges = values.map(r => ({ start: Number(r.start), end: Number(r.end) }));
    const error = values.some(r => !r.start.trim() || !r.end.trim()) ? "number"
      : values.length ? validateRanges(ranges, media.source_duration ?? NaN) : null;
    if (error) validationErrors[id] = error;
    else if (ranges.length) draft[id] = ranges.sort((a, b) => a.start - b.start);
  }
  return { draft, photoDurations, validationErrors };
}

export function usePackageEditor(): PackageEditorState {
  const { status, generation, invalidate, client } = useSession();
  const [data, setData] = useState<Data>(empty);
  const [offline, setOffline] = useState(!navigator.onLine);
  const current = useRef(data);
  const alive = useRef(false);
  const read = useRef<AbortController | null>(null), write = useRef<AbortController | null>(null);
  const update = useCallback((next: Data) => { current.current = next; setData(next); }, []);
  const accept = useCallback((snapshot: ActiveEditorOut, explicit: boolean, ownWrite?: ActiveEditorOut) => {
    const old = current.current, fresh = inputs(snapshot), hadDraft = dirty(old);
    const otherPackage = old.baseFolder !== null && (old.baseFolder !== snapshot.package.folder_name || old.snapshot?.package.id !== snapshot.package.id);
    const nextInputs = { ...fresh };
    if (hadDraft) for (const id of Object.keys(old.draftInputs)) {
      if (changed(old, id)) nextInputs[id] = old.draftInputs[id];
    }
    const conflict = hadDraft && (ownWrite ? writeFingerprint(ownWrite) !== writeFingerprint(snapshot) : fingerprint(old.snapshot) !== fingerprint(snapshot));
    const readRequired = explicit ? false : old.readRequired;
    update({ ...old, snapshot, draftInputs: nextInputs,
      base: hadDraft && !explicit && (!ownWrite || conflict) ? old.base : fresh,
      baseFolder: hadDraft && otherPackage ? old.baseFolder : snapshot.package.folder_name,
      stale: readRequired || otherPackage && hadDraft || !explicit && (conflict || old.stale),
      readRequired, loading: false, error: readRequired ? old.error : explicit || ownWrite ? null : old.error,
    });
  }, [update]);
  const load = useCallback(async (explicit = false, signal?: AbortSignal, ownWrite?: ActiveEditorOut) => {
    if (!alive.current || !navigator.onLine || current.current.pendingClear || current.current.busy && !ownWrite) return;
    read.current?.abort();
    const controller = new AbortController(); read.current = controller;
    const cancel = () => controller.abort(); signal?.addEventListener("abort", cancel, { once: true });
    update({ ...current.current, loading: true });
    try {
      const snapshot = await api.packageEditor(controller.signal);
      if (alive.current && !controller.signal.aborted) accept(snapshot, explicit, ownWrite);
    } catch (error) {
      if (!alive.current || controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) { update(empty()); invalidate(); }
      else if (error instanceof ApiError && error.status === 404) {
        update({ ...current.current, snapshot: null, loading: false, stale: dirty(current.current), error: null });
      } else update({ ...current.current, loading: false, error: "read" });
    } finally {
      signal?.removeEventListener("abort", cancel);
      if (read.current === controller && alive.current && current.current.loading) update({ ...current.current, loading: false });
    }
  }, [accept, invalidate, update]);
  useEffect(() => {
    alive.current = true;
    const pendingClear = client ? rememberedClear(client.id) : null;
    update({ ...empty(), pendingClear, error: pendingClear ? "cleanup" : null });
    const stop = status === "paired" ? startLiveRefresh(signal => load(false, signal)) : () => {};
    const connectivity = () => setOffline(!navigator.onLine);
    window.addEventListener("online", connectivity); window.addEventListener("offline", connectivity);
    return () => { alive.current = false; stop(); read.current?.abort(); write.current?.abort();
      window.removeEventListener("online", connectivity); window.removeEventListener("offline", connectivity); };
  }, [status, generation, client?.id, load, update]);
  const mutate = useCallback(async (operation: (folder: string, signal: AbortSignal) => Promise<unknown>, change: WriteChange): Promise<boolean> => {
    const old = current.current;
    const clearing = change.kind === "clear";
    const target = old.pendingClear ?? old.snapshot?.package;
    if (!alive.current || !navigator.onLine || old.busy || !target
      || !clearing && (old.stale || old.readRequired || !old.snapshot)) return false;
    const expected = old.snapshot ? expectedWrite(old.snapshot, change) : undefined;
    read.current?.abort();
    const controller = new AbortController(); write.current = controller;
    const pendingClear = clearing ? { id: target.id, folder_name: target.folder_name } : old.pendingClear;
    if (clearing) rememberClear(client?.id, pendingClear);
    update({ ...old, pendingClear, busy: true, loading: false, error: null });
    try {
      await operation(target.folder_name, controller.signal);
      if (!alive.current || controller.signal.aborted) return false;
      if (clearing) { rememberClear(client?.id, null); update(empty()); return true; }
      if (change.kind === "selections") update({ ...current.current, base: current.current.draftInputs });
      await load(false, undefined, expected);
      // Acknowledged writes may succeed even if the follow-up read fails, but
      // further mutations wait for an explicit successful read in that case.
      if (current.current.error === "read") update({ ...current.current, stale: true, readRequired: true });
      return true;
    } catch (error) {
      if (!alive.current || controller.signal.aborted) return false;
      if (error instanceof ApiError && error.status === 401) { update(empty()); invalidate(); }
      else {
        const definite = error instanceof ApiError && [404, 409, 422].includes(error.status);
        if (clearing && !definite) {
          update({ ...current.current, error: "cleanup", stale: true, readRequired: true });
          return false;
        }
        if (clearing) rememberClear(client?.id, null);
        update({ ...current.current, stale: !definite || error instanceof ApiError && error.status === 409,
          pendingClear: clearing ? null : current.current.pendingClear,
          readRequired: !definite,
          error: definite ? error.status === 422 ? "invalid" : change.kind === "render" ? "render" : "conflict" : "uncertain" });
      }
      return false;
    } finally { if (write.current === controller && alive.current) { write.current = null; update({ ...current.current, busy: false }); } }
  }, [client?.id, invalidate, load, update]);
  const setRanges = useCallback((id: string, ranges: VideoRange[]) => {
    if (current.current.busy || current.current.stale) return;
    update({ ...current.current, draftInputs: { ...current.current.draftInputs,
      [id]: [...ranges].sort((a, b) => a.start - b.start).map(r => ({ start: String(r.start), end: String(r.end) })) } });
  }, [update]);
  const setInput = useCallback((id: string, index: number, bound: "start" | "end", value: string) => {
    const old = current.current;
    if (old.busy || old.stale || !old.draftInputs[id]?.[index]) return;
    update({ ...old, draftInputs: { ...old.draftInputs,
      [id]: old.draftInputs[id].map((r, i) => i === index ? { ...r, [bound]: value } : r) } });
  }, [update]);
  const discard = useCallback((id?: string) => {
    const old = current.current;
    if (old.busy) return;
    const fresh = old.snapshot ? inputs(old.snapshot) : {};
    update({ ...old, draftInputs: id ? { ...old.draftInputs, [id]: fresh[id] ?? [] } : fresh,
      base: id ? { ...old.base, [id]: fresh[id] ?? [] } : fresh,
      baseFolder: id ? old.baseFolder : old.snapshot?.package.folder_name ?? null,
      stale: old.readRequired || (id ? old.stale : false), error: old.readRequired ? old.error : null });
  }, [update]);
  const save = useCallback(async () => {
    const old = current.current, values = numeric(old);
    if (!old.snapshot || !dirty(old) || Object.keys(values.validationErrors).length) return false;
    const total = proposedDuration(old.snapshot, values.draft, values.photoDurations);
    if (total === null || total > old.snapshot.montage.max_duration_seconds) return false;
    return mutate((folder, signal) => api.saveSelections({ expected_folder_name: folder, selections: values.draft,
      ...(Object.keys(values.photoDurations).length ? { photo_durations: values.photoDurations } : {}) }, signal),
    { kind: "selections", selections: values.draft, photos: values.photoDurations });
  }, [mutate]);
  const values = numeric(data), total = data.snapshot && !Object.keys(values.validationErrors).length ? proposedDuration(data.snapshot, values.draft, values.photoDurations) : null;
  const saveBlockedReason: SaveBlockedReason = data.busy || data.loading ? "busy" : offline ? "offline" : data.stale || !data.snapshot ? "refresh"
    : !dirty(data) ? "unchanged" : Object.keys(values.validationErrors).length ? "invalid" : total === null ? "duration"
    : total > data.snapshot.montage.max_duration_seconds ? "limit" : null;
  return { ...data, ...values, offline, dirty: dirty(data), proposedTotal: total,
    canSave: saveBlockedReason === null, saveBlockedReason,
    isDirty: id => changed(current.current, id), setRanges, setInput, save, discard,
    setPhotoDuration: (id, value) => setInput(id, 0, "end", value),
    renderPreview: () => mutate((folder, signal) => api.renderPackage(folder, current.current.snapshot?.render_status === "failed", signal), { kind: "render" }),
    clearPackage: async () => {
      let result: ClearPackageOut | null = null;
      const succeeded = await mutate(async (folder, signal) => {
        const target = current.current.pendingClear!;
        result = await api.clearPackage({ expected_folder_name: folder, expected_package_id: target.id, confirmed: true }, signal);
      }, { kind: "clear" });
      return succeeded ? result : null;
    },
    refresh: () => load(true),
    reorder: order => mutate((folder, signal) => api.saveOrder(order, folder, signal), { kind: "order", order }),
    remove: id => changed(current.current, id) ? Promise.resolve(false) : mutate((folder, signal) => api.removeMedia(id, folder, signal), { kind: "remove", id }),
    restore: id => mutate((folder, signal) => api.restoreMedia(id, folder, signal), { kind: "restore", id }),
  };
}
