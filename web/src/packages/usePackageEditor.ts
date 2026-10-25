import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ActiveEditorOut, ClearPackageOut } from "../api/openapi";
import { live, startLiveRefresh } from "../live";
import { useLivePhase } from "../liveProvider";
import { useSession } from "../session";
import { deleteDraft, listDrafts, reconcileDraft, resolveDraftConflict, sameGroup, serverGroup, writeDraft,
  type DraftKey, type StoredDraft } from "./drafts";
import { proposedDuration, validateRanges, type RangeInput, type SelectionMap, type VideoRange } from "./ranges";

type EditorError = "read" | "uncertain" | "conflict" | "invalid" | "limit" | "render" | "cleanup" | null;
type ClearTarget = { id: number; folder_name: string; content_revision: number };
type PersistenceError = "unavailable" | "conflict" | "corrupt" | null;
type SaveBlockedReason = "unchanged" | "busy" | "offline" | "refresh" | "invalid" | "duration" | "limit" | "storage" | null;
interface Data {
  draftKey: DraftKey | null;
  storedDraft: StoredDraft | null;
  restoring: boolean;
  persisting: boolean;
  persistenceError: PersistenceError;
  conflicts: Record<string, Record<string, unknown>>;
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
  canEdit: boolean;
  persistenceError: PersistenceError;
  persisting: boolean;
  restoring: boolean;
  draftFolder: string | null;
  conflicts: Record<string, Record<string, unknown>>;
  resolveConflict(key: string, choice: "server" | "local"): void;
  retryDraftPersistence(): Promise<void>;
  loadStoredDraft(): Promise<void>;
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
  save(id: string): Promise<boolean>;
  canSaveMedia(id: string): boolean;
  saveBlockedReasonFor(id: string): SaveBlockedReason;
  retrySectionPreview(id: string): Promise<boolean>;
  discard(id?: string): void;
  refresh(): Promise<void>;
  reorder(order: string[]): Promise<boolean>;
  remove(id: string, confirmedDiscard?: boolean): Promise<boolean>;
  restore(id: string): Promise<boolean>;
}
const empty = (): Data => ({ draftKey: null, storedDraft: null, restoring: false, persisting: false, persistenceError: null, conflicts: {}, pendingClear: null, snapshot: null, draftInputs: {}, base: {}, baseFolder: null, stale: false, readRequired: false, loading: false, busy: false, error: null });
const clearKey = (clientId: number) => `aisomedo.package-clear.v1:${clientId}`;
function rememberedClear(clientId: number): ClearTarget | null {
  try {
    const value = JSON.parse(localStorage.getItem(clearKey(clientId)) ?? "null");
    return value && Number.isSafeInteger(value.id) && value.id > 0 && typeof value.folder_name === "string" && Number.isSafeInteger(value.content_revision) && value.content_revision > 0 ? value : null;
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
const dirty = (data: Data) => Object.keys(data.draftInputs).some(id => changed(data, id))
  || Object.keys(data.storedDraft?.groups ?? {}).some(key => !key.startsWith("video:") && !key.startsWith("photo:"));

function baselineInputs(draft: StoredDraft): Record<string, RangeInput[]> {
  const base: Record<string, RangeInput[]> = {};
  for (const [key, group] of Object.entries(draft.groups)) {
    const id = key.slice(key.indexOf(":") + 1);
    if (key.startsWith("video:") && Array.isArray(group.base.ranges)) base[id] = group.base.ranges.map(value => ({ start: String(value.start), end: String(value.end) }));
    if (key.startsWith("photo:")) base[id] = [{ start: "0", end: String(group.base.seconds) }];
  }
  return base;
}

function editedDraft(data: Data): StoredDraft | null {
  const snapshot = data.snapshot;
  if (!snapshot && !data.storedDraft) return null;
  const groups = { ...data.storedDraft?.groups }, edited: Record<string, RangeInput[]> = {};
  for (const [id, rows] of Object.entries(data.draftInputs)) {
    const media = snapshot?.media.find(value => value.media_id === id);
    if (!media) { if (data.storedDraft?.inputs[id]) edited[id] = rows; continue; }
    const key = `${media.is_video ? "video" : "photo"}:${id}`;
    if (!changed(data, id)) { delete groups[key]; continue; }
    const number = (value: string) => value.trim() && Number.isFinite(Number(value)) ? Number(value) : value;
    const proposed = media.is_video ? { ranges: rows.map(row => ({ start: number(row.start), end: number(row.end) })) }
      : { seconds: number(rows[0]?.end ?? "") };
    groups[key] = { base: groups[key]?.base ?? serverGroup(snapshot!, key), proposed };
    edited[id] = structuredClone(rows);
  }
  const uncertain = data.storedDraft?.uncertain ?? false;
  if (!Object.keys(groups).length && !uncertain && !data.storedDraft?.pendingRemovals?.length) return null;
  return { schemaVersion: 1, localRevision: data.storedDraft?.localRevision ?? 0,
    folderName: data.storedDraft?.folderName ?? snapshot!.package.folder_name,
    baseContentRevision: data.storedDraft?.baseContentRevision ?? snapshot!.content_revision,
    groups, inputs: edited, uncertain, pendingRemovals: data.storedDraft?.pendingRemovals ?? [] };
}
type WriteChange = { kind: "selections"; selections: SelectionMap; photos: Record<string, number> } | { kind: "order"; order: string[] } | { kind: "remove" | "restore" | "retry"; id: string } | { kind: "render" | "clear" };
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

function cardValues(data: Data, id: string) {
  return numeric({ ...data, draftInputs: data.snapshot
    ? { ...inputs(data.snapshot), [id]: data.draftInputs[id] ?? [] } : {} });
}

function cardSaveReason(data: Data, id: string, enabled: boolean): SaveBlockedReason {
  if (data.busy || data.loading || data.restoring) return "busy";
  if (data.persistenceError) return "storage";
  if (!enabled || !navigator.onLine || live.getSnapshot() !== "live") return "offline";
  if (data.stale || data.readRequired || !data.snapshot) return "refresh";
  if (!data.snapshot.media.some(m => m.media_id === id && m.status === "finalized") || !changed(data, id)) return "unchanged";
  const values = cardValues(data, id);
  if (values.validationErrors[id]) return "invalid";
  const total = proposedDuration(data.snapshot, values.draft, values.photoDurations);
  return total === null ? "duration" : total > data.snapshot.montage.max_duration_seconds ? "limit" : null;
}

export function usePackageEditor(enabled = true): PackageEditorState {
  const phase = useLivePhase();
  const { status, generation, invalidate, client } = useSession();
  const [data, setData] = useState<Data>(empty);
  const [offline, setOffline] = useState(!navigator.onLine);
  const current = useRef(data);
  const alive = useRef(false);
  const lifetime = useRef(0);
  const revision = useRef(0);
  const persistence = useRef<Promise<void>>(Promise.resolve());
  const restoring = useRef<Promise<void>>(Promise.resolve());
  const read = useRef<AbortController | null>(null), write = useRef<AbortController | null>(null);
  const update = useCallback((next: Data) => { current.current = next; setData(next); }, []);
  const persist = useCallback((next: Data): Promise<boolean> => {
    const key = next.draftKey, draft = next.storedDraft, epoch = lifetime.current;
    if (!key) return Promise.resolve(false);
    update({ ...next, persisting: true });
    let succeeded = false;
    const work = persistence.current.then(async () => {
      if (epoch !== lifetime.current || current.current.persistenceError) return;
      try {
        if (draft) revision.current = await writeDraft(key, revision.current, draft);
        else { await deleteDraft(key, revision.current); revision.current = 0; }
        succeeded = true;
      } catch (error) {
        if (alive.current && epoch === lifetime.current) update({ ...current.current,
          persistenceError: error instanceof Error && error.message === "draft_conflict" ? "conflict"
            : error instanceof Error && error.message === "draft_corrupt" ? "corrupt" : "unavailable" });
      }
    });
    persistence.current = work;
    return work.then(() => {
      if (alive.current && epoch === lifetime.current && persistence.current === work) update({ ...current.current,
        persisting: false, storedDraft: current.current.storedDraft && { ...current.current.storedDraft, localRevision: revision.current } });
      return succeeded;
    });
  }, [update]);
  const accept = useCallback(async (snapshot: ActiveEditorOut, explicit: boolean, ownWrite?: ActiveEditorOut) => {
    const old = current.current, fresh = inputs(snapshot);
    const key = old.draftKey ?? (client ? { origin: window.location.origin, clientId: client.id, packageId: snapshot.package.id } : null);
    let draft = editedDraft(old);
    if (draft?.uncertain && (explicit || ownWrite)) draft = { ...draft, uncertain: false };
    const result = key && draft ? reconcileDraft(key, draft, snapshot) : { draft: null, conflicts: {}, applicable: true };
    const retained = result.draft;
    const readRequired = old.readRequired && !explicit && !ownWrite;
    const next: Data = { ...old, snapshot, draftKey: result.applicable && !retained && client
      ? { origin: window.location.origin, clientId: client.id, packageId: snapshot.package.id } : key,
      storedDraft: retained, conflicts: result.conflicts,
      draftInputs: { ...fresh, ...retained?.inputs }, base: { ...fresh, ...(retained ? baselineInputs(retained) : {}) },
      baseFolder: retained?.folderName ?? snapshot.package.folder_name,
      stale: readRequired || !result.applicable || Object.keys(result.conflicts).length > 0,
      readRequired, loading: false, error: readRequired ? old.error : null };
    // Delete only the acknowledged/reconciled local revision, never another tab's.
    if (!sameGroup(old.storedDraft, retained) && old.draftKey) {
      await persist({ ...next, draftKey: old.draftKey });
      if (alive.current && !current.current.persistenceError) update({ ...current.current, draftKey: next.draftKey });
    } else update(next);
  }, [client?.id, persist, update]);
  const load = useCallback(async (explicit = false, signal?: AbortSignal, ownWrite?: ActiveEditorOut) => {
    await restoring.current;
    if (signal?.aborted || !alive.current || !navigator.onLine || current.current.pendingClear || current.current.busy && !ownWrite) return;
    read.current?.abort();
    const controller = new AbortController(); read.current = controller;
    const cancel = () => controller.abort(); signal?.addEventListener("abort", cancel, { once: true });
    update({ ...current.current, loading: true });
    try {
      const snapshot = await api.packageEditor(controller.signal);
      if (alive.current && !controller.signal.aborted) await accept(snapshot, explicit, ownWrite);
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
  const loadStoredDraft = useCallback(async () => {
    if (!client) return;
    const epoch = lifetime.current;
    update({ ...current.current, restoring: true });
    await persistence.current;
    try {
      const rows = await listDrafts({ origin: window.location.origin, clientId: client.id });
      if (!alive.current || epoch !== lifetime.current) return;
      const selected = current.current.draftKey ? rows.find(row => row.packageId === current.current.draftKey!.packageId) : rows[0];
      revision.current = selected?.draft.localRevision ?? 0;
      const draft = selected?.draft ?? null;
      update({ ...current.current, restoring: false, persistenceError: null, storedDraft: draft,
        draftKey: selected ? { origin: window.location.origin, clientId: client.id, packageId: selected.packageId } : current.current.draftKey,
        draftInputs: { ...(current.current.snapshot ? inputs(current.current.snapshot) : {}), ...draft?.inputs },
        base: { ...(current.current.snapshot ? inputs(current.current.snapshot) : {}), ...(draft ? baselineInputs(draft) : {}) },
        baseFolder: draft?.folderName ?? current.current.snapshot?.package.folder_name ?? null,
        readRequired: false, stale: !!draft });
    } catch (error) {
      if (alive.current && epoch === lifetime.current) update({ ...current.current, restoring: false,
        persistenceError: error instanceof Error && error.message === "draft_corrupt" ? "corrupt" : "unavailable" });
    }
  }, [client?.id, update]);
  useEffect(() => {
    alive.current = true;
    lifetime.current++; revision.current = 0;
    const pendingClear = client ? rememberedClear(client.id) : null;
    update({ ...empty(), pendingClear, error: pendingClear ? "cleanup" : null });
    restoring.current = loadStoredDraft();
    const connectivity = () => setOffline(!navigator.onLine);
    window.addEventListener("online", connectivity); window.addEventListener("offline", connectivity);
    return () => { alive.current = false; read.current?.abort(); write.current?.abort();
      window.removeEventListener("online", connectivity); window.removeEventListener("offline", connectivity); };
  }, [status, generation, client?.id, loadStoredDraft, update]);
  useEffect(() => {
    if (!enabled || status !== "paired") return;
    const stop = startLiveRefresh(async signal => {
      await load(false, signal);
      if (current.current.error === "read") throw new Error("editor snapshot unavailable");
    }, ["package:*", "settings", "publication"]);
    return () => {
      stop(); read.current?.abort();
      if (alive.current) update({ ...current.current, stale: true });
    };
  }, [enabled, status, generation, load, update]);
  const mutate = useCallback(async (operation: (folder: string, signal: AbortSignal) => Promise<unknown>, change: WriteChange): Promise<boolean> => {
    const old = current.current;
    const clearing = change.kind === "clear";
    const target = old.pendingClear ?? old.snapshot?.package;
    if (!enabled || !alive.current || !navigator.onLine || live.getSnapshot() !== "live" || old.busy || !target
      || old.restoring || old.persistenceError || !clearing && (old.stale || old.readRequired || !old.snapshot)) return false;
    const expected = old.snapshot ? expectedWrite(old.snapshot, change) : undefined;
    read.current?.abort();
    const controller = new AbortController(); write.current = controller;
    const pendingClear = clearing ? { id: target.id, folder_name: target.folder_name, content_revision: old.pendingClear?.content_revision ?? old.snapshot!.content_revision } : old.pendingClear;
    if (clearing) rememberClear(client?.id, pendingClear);
    update({ ...old, pendingClear, busy: true, loading: false, error: null });
    try {
      const draft = editedDraft(old) ?? { schemaVersion: 1 as const, localRevision: revision.current,
        folderName: target.folder_name, baseContentRevision: old.snapshot?.content_revision ?? old.pendingClear!.content_revision,
        groups: {}, inputs: {}, uncertain: false };
      if (!await persist({ ...current.current, storedDraft: { ...draft, uncertain: true,
        pendingRemovals: change.kind === "remove" ? [...new Set([...(draft.pendingRemovals ?? []), change.id])] : draft.pendingRemovals } })) return false;
      if (!alive.current || controller.signal.aborted || live.getSnapshot() !== "live") return false;
      const response = await operation(target.folder_name, controller.signal);
      if (!alive.current || controller.signal.aborted) return false;
      if (clearing) {
        await persist({ ...current.current, storedDraft: null });
        rememberClear(client?.id, null); update({ ...empty(), persistenceError: current.current.persistenceError }); return true;
      }
      if (change.kind === "remove") {
        const acknowledged = current.current;
        const fresh = inputs(acknowledged.snapshot!);
        const groups = { ...acknowledged.storedDraft?.groups }, conflicts = { ...acknowledged.conflicts };
        for (const key of [`video:${change.id}`, `photo:${change.id}`]) { delete groups[key]; delete conflicts[key]; }
        const next = { ...acknowledged, conflicts,
          storedDraft: acknowledged.storedDraft && { ...acknowledged.storedDraft, groups, uncertain: false,
            pendingRemovals: acknowledged.storedDraft.pendingRemovals?.filter(id => id !== change.id) },
          draftInputs: { ...acknowledged.draftInputs, [change.id]: fresh[change.id] ?? [] },
          base: { ...acknowledged.base, [change.id]: fresh[change.id] ?? [] } };
        await persist({ ...next, storedDraft: editedDraft(next) });
      }
      if ((change.kind === "selections" || change.kind === "retry") && response && typeof response === "object" && "package" in response) await accept(response as ActiveEditorOut, false, expected);
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
        if (definite && current.current.storedDraft) await persist({ ...current.current,
          storedDraft: { ...current.current.storedDraft, uncertain: false,
            pendingRemovals: change.kind === "remove" ? current.current.storedDraft.pendingRemovals?.filter(id => id !== change.id) : current.current.storedDraft.pendingRemovals } });
        if (change.kind === "retry" && error instanceof ApiError && error.status === 409) await load(true, undefined, expected);
      }
      return false;
    } finally { if (write.current === controller && alive.current) { write.current = null; update({ ...current.current, busy: false }); } }
  }, [enabled, accept, client?.id, invalidate, load, persist, update]);
  const edit = useCallback((next: Data) => {
    void persist({ ...next, storedDraft: editedDraft(next) });
  }, [persist]);
  const setRanges = useCallback((id: string, ranges: VideoRange[]) => {
    if (!navigator.onLine || live.getSnapshot() !== "live" || current.current.busy || current.current.restoring || current.current.stale || !current.current.snapshot) return;
    edit({ ...current.current, draftInputs: { ...current.current.draftInputs,
      [id]: [...ranges].sort((a, b) => a.start - b.start).map(r => ({ start: String(r.start), end: String(r.end) })) } });
  }, [edit]);
  const setInput = useCallback((id: string, index: number, bound: "start" | "end", value: string) => {
    const old = current.current;
    if (!navigator.onLine || live.getSnapshot() !== "live" || old.busy || old.restoring || old.stale || !old.snapshot || !old.draftInputs[id]?.[index]) return;
    edit({ ...old, draftInputs: { ...old.draftInputs,
      [id]: old.draftInputs[id].map((r, i) => i === index ? { ...r, [bound]: value } : r) } });
  }, [edit]);
  const discard = useCallback((id?: string) => {
    const old = current.current;
    if (live.getSnapshot() !== "live" || old.busy) return;
    // A draft retained from a replaced package is deleted before the editor is
    // rebound, so later edits cannot be written under the old package key.
    const rollover = !!old.draftKey && !!old.snapshot && old.draftKey.packageId !== old.snapshot.package.id;
    const fresh = old.snapshot ? inputs(old.snapshot) : {};
    const groups = { ...old.storedDraft?.groups }, conflicts = rollover ? {} : { ...old.conflicts };
    for (const key of Object.keys(groups)) if (rollover || !id || key === `video:${id}` || key === `photo:${id}`) { delete groups[key]; delete conflicts[key]; }
    const next = { ...old, storedDraft: rollover ? null : old.storedDraft && { ...old.storedDraft, groups,
      pendingRemovals: id ? old.storedDraft.pendingRemovals?.filter(value => value !== id) : [] }, conflicts,
      draftInputs: id && !rollover ? { ...old.draftInputs, [id]: fresh[id] ?? [] } : fresh,
      base: id && !rollover ? { ...old.base, [id]: fresh[id] ?? [] } : fresh,
      baseFolder: id && !rollover ? old.baseFolder : old.snapshot?.package.folder_name ?? null,
      stale: old.readRequired || (id && !rollover ? old.stale : false), error: old.readRequired ? old.error : null };
    if (rollover) {
      void persist({ ...old, storedDraft: null });
      update({ ...next, draftKey: { ...old.draftKey!, packageId: old.snapshot!.package.id } });
    } else edit(next);
  }, [edit, persist, update]);
  const save = useCallback(async (id: string) => {
    const old = current.current, values = cardValues(old, id);
    if (cardSaveReason(old, id, enabled)) return false;
    const draft = editedDraft(old);
    const media = old.snapshot!.media.find(m => m.media_id === id)!;
    const key = `${media.is_video ? "video" : "photo"}:${id}`, group = draft?.groups[key];
    if (!draft || !group) return false;
    return mutate((folder, signal) => api.savePackageEdits({ expected_folder_name: folder,
      expected_package_id: old.snapshot!.package.id, base_content_revision: draft.baseContentRevision,
      changes: [{ key, ...group }] }, signal),
    { kind: "selections", selections: values.draft, photos: values.photoDurations });
  }, [enabled, mutate]);
  const values = numeric(data), total = data.snapshot && !Object.keys(values.validationErrors).length ? proposedDuration(data.snapshot, values.draft, values.photoDurations) : null;
  const saveBlockedReason: SaveBlockedReason = data.busy || data.loading || data.restoring ? "busy" : data.persistenceError ? "storage" : !enabled || offline || phase !== "live" ? "offline" : data.stale || !data.snapshot ? "refresh"
    : !dirty(data) ? "unchanged" : Object.keys(values.validationErrors).length ? "invalid" : total === null ? "duration"
    : total > data.snapshot.montage.max_duration_seconds ? "limit" : null;
  return { ...data, ...values, offline: offline || phase !== "live", dirty: dirty(data), proposedTotal: total,
    canEdit: enabled && phase === "live" && !data.busy && !data.restoring && !data.stale && !!data.snapshot,
    draftFolder: data.storedDraft?.folderName ?? null,
    retryDraftPersistence: async () => {
      if (current.current.persistenceError !== "unavailable") return;
      await persist({ ...current.current, persistenceError: null, storedDraft: editedDraft(current.current) });
    },
    loadStoredDraft,
    resolveConflict: (key, choice) => {
      const old = current.current;
      if (live.getSnapshot() !== "live" || old.busy || !old.storedDraft || !old.snapshot || !old.conflicts[key]) return;
      const draft = resolveDraftConflict(old.storedDraft, key, old.conflicts[key], choice, old.snapshot.content_revision);
      const conflicts = { ...old.conflicts }; delete conflicts[key];
      const fresh = inputs(old.snapshot);
      void persist({ ...old, storedDraft: draft, conflicts, stale: Object.keys(conflicts).length > 0,
        draftInputs: { ...fresh, ...draft?.inputs }, base: { ...fresh, ...(draft ? baselineInputs(draft) : {}) } });
    },
    canSave: saveBlockedReason === null, saveBlockedReason,
    canSaveMedia: id => cardSaveReason(data, id, enabled) === null,
    saveBlockedReasonFor: id => cardSaveReason(data, id, enabled),
    retrySectionPreview: id => {
      const snapshot = current.current.snapshot, preview = snapshot?.media.find(m => m.media_id === id)?.section_preview;
      if (!snapshot || preview?.status !== "failed" || !preview.generation) return Promise.resolve(false);
      return mutate((folder, signal) => api.retrySectionPreview(id, { expected_package_id: snapshot.package.id,
        expected_folder_name: folder, expected_generation: preview.generation! }, signal), { kind: "retry", id });
    },
    isDirty: id => changed(current.current, id), setRanges, setInput, save, discard,
    setPhotoDuration: (id, value) => setInput(id, 0, "end", value),
    renderPreview: () => mutate((folder, signal) => api.renderPackage(folder, current.current.snapshot?.render_status === "failed", current.current.snapshot!, signal), { kind: "render" }),
    clearPackage: async () => {
      let result: ClearPackageOut | null = null;
      const succeeded = await mutate(async (folder, signal) => {
        const target = current.current.pendingClear!;
        result = await api.clearPackage({ expected_folder_name: folder, expected_package_id: target.id, confirmed: true }, { package: { id: target.id }, content_revision: target.content_revision }, signal);
      }, { kind: "clear" });
      return succeeded ? result : null;
    },
    refresh: () => load(true),
    reorder: order => mutate((folder, signal) => api.saveOrder(order, folder, current.current.snapshot!, signal), { kind: "order", order }),
    remove: (id, confirmedDiscard = false) => changed(current.current, id) && !confirmedDiscard ? Promise.resolve(false) : mutate((folder, signal) => api.removeMedia(id, folder, current.current.snapshot!, signal), { kind: "remove", id }),
    restore: id => mutate((folder, signal) => api.restoreMedia(id, folder, current.current.snapshot!, signal), { kind: "restore", id }),
  };
}
