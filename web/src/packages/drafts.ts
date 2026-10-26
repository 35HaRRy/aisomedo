import type { ActiveEditorOut } from "../api/openapi";
import type { RangeInput } from "./ranges";

export type DraftKey = { origin: string; clientId: number; packageId: number };
type Identity = Pick<DraftKey, "origin" | "clientId">;
export type DraftGroup = { base: Record<string, unknown>; proposed: Record<string, unknown> };
export type StoredDraft = {
  schemaVersion: 1;
  localRevision: number;
  folderName: string;
  baseContentRevision: number;
  groups: Record<string, DraftGroup>;
  inputs: Record<string, RangeInput[]>;
  uncertain: boolean;
  pendingRemovals?: string[];
};
type Tombstone = { schemaVersion: 1; localRevision: number; deleted: true };
type StoredEntry = StoredDraft | Tombstone;
type Outcome<T> = { write: boolean; next: StoredEntry | null; result: T };
export type DraftTransaction = <T>(key: string, operation: (current: unknown) => Outcome<T>) => Promise<T>;
type Entries = (prefix: string) => Promise<[string, unknown][]>;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object"
  && !Array.isArray(value) && [null, Object.prototype].includes(Object.getPrototypeOf(value));
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const safeId = (key: string) => !!key && !["__proto__", "constructor", "prototype"].includes(key);
const tombstone = (value: unknown): value is Tombstone => record(value)
  && Object.keys(value).sort().join() === "deleted,localRevision,schemaVersion"
  && value.schemaVersion === 1 && positive(value.localRevision) && value.deleted === true;
const entryRevision = (value: unknown) => value === null ? 0 : tombstone(value) ? value.localRevision : parseDraft(value).localRevision;

export function sameGroup(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((value, i) => sameGroup(value, b[i]));
  if (record(a) && record(b)) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(key => Object.prototype.hasOwnProperty.call(b, key) && sameGroup(a[key], b[key]));
  }
  return false;
}

export function serverGroup(snapshot: ActiveEditorOut, key: string): Record<string, unknown> {
  if (key === "order") return { ids: [...snapshot.montage.order] };
  const id = key.slice(key.indexOf(":") + 1), media = snapshot.media.find(value => value.media_id === id);
  if (!media || media.status !== "finalized") return { status: "unavailable" };
  if (key.startsWith("video:") && media.is_video) return { ranges: structuredClone(snapshot.montage.selections[id] ?? []) };
  if (key.startsWith("photo:") && !media.is_video) return { seconds: media.effective_duration };
  return { status: "unavailable" };
}

export function reconcileDraft(key: DraftKey, draft: StoredDraft, snapshot: ActiveEditorOut) {
  const next = structuredClone(draft), conflicts: Record<string, Record<string, unknown>> = {};
  const applicable = key.packageId === snapshot.package.id && draft.folderName === snapshot.package.folder_name
    && snapshot.package.status === "active";
  if (!applicable) return { draft: next, conflicts, applicable };
  next.pendingRemovals = (next.pendingRemovals ?? []).filter(id => {
    if (!snapshot.media.some(media => media.media_id === id && media.status === "removed")) return true;
    delete next.groups[`video:${id}`]; delete next.groups[`photo:${id}`]; delete next.inputs[id];
    return false;
  });
  const groups = Object.entries(next.groups);
  for (const [name, group] of groups) {
    const current = serverGroup(snapshot, name);
    if (sameGroup(current, group.proposed)) {
      delete next.groups[name];
      if (name.startsWith("video:") || name.startsWith("photo:")) delete next.inputs[name.slice(name.indexOf(":") + 1)];
    } else if (!sameGroup(current, group.base)) conflicts[name] = current;
  }
  if (groups.length && !Object.keys(next.groups).length) next.uncertain = false;
  return { draft: Object.keys(next.groups).length || next.uncertain || next.pendingRemovals.length ? next : null, conflicts, applicable };
}

export function resolveDraftConflict(
  draft: StoredDraft, key: string, current: Record<string, unknown>, choice: "server" | "local", revision: number,
): StoredDraft | null {
  const next = structuredClone(draft), group = next.groups[key];
  if (!group) throw new Error("draft_conflict");
  if (choice === "local") {
    if (current.status === "unavailable") throw new Error("draft_unavailable");
    group.base = structuredClone(current);
  } else {
    delete next.groups[key];
    if (key.startsWith("video:") || key.startsWith("photo:")) delete next.inputs[key.slice(key.indexOf(":") + 1)];
  }
  next.baseContentRevision = revision; next.uncertain = false;
  return Object.keys(next.groups).length ? next : null;
}

function parseDraft(value: unknown, allowZero = false): StoredDraft {
  if (!record(value) || Object.keys(value).filter(key => key !== "pendingRemovals").sort().join() !== "baseContentRevision,folderName,groups,inputs,localRevision,schemaVersion,uncertain"
    || value.schemaVersion !== 1 || !Number.isSafeInteger(value.localRevision) || Number(value.localRevision) < (allowZero ? 0 : 1)
    || typeof value.folderName !== "string" || !value.folderName || !positive(value.baseContentRevision)
    || !record(value.groups) || !record(value.inputs) || typeof value.uncertain !== "boolean") throw new Error("draft_corrupt");
  if (value.pendingRemovals !== undefined && (!Array.isArray(value.pendingRemovals)
    || value.pendingRemovals.some(id => typeof id !== "string" || !safeId(id)))) throw new Error("draft_corrupt");
  for (const [key, group] of Object.entries(value.groups)) {
    const field = key.startsWith("video:") ? "ranges" : key.startsWith("photo:") ? "seconds"
      : ({ order: "ids", caption: "text", branding: "settings" } as Record<string, string>)[key];
    if (!field || !record(group) || Object.keys(group).sort().join() !== "base,proposed"
      || !record(group.base) || !record(group.proposed) || Object.keys(group.base).join() !== field
      || Object.keys(group.proposed).join() !== field) throw new Error("draft_corrupt");
  }
  for (const [id, rows] of Object.entries(value.inputs)) {
    if (!safeId(id) || !Array.isArray(rows) || rows.some(row => !record(row)
      || Object.keys(row).sort().join() !== "end,start" || typeof row.start !== "string" || typeof row.end !== "string")) throw new Error("draft_corrupt");
  }
  return structuredClone(value as StoredDraft);
}

function scope(identity: Identity): string {
  if (!positive(identity.clientId) || new URL(identity.origin).origin !== identity.origin) throw new Error("draft_identity");
  return JSON.stringify([identity.origin, identity.clientId]).slice(0, -1) + ",";
}
function storageKey(key: DraftKey) {
  if (!positive(key.packageId)) throw new Error("draft_identity");
  return scope(key) + key.packageId + "]";
}

export function createDraftStore(transaction: DraftTransaction, entries: Entries) {
  return {
    readDraft: (key: DraftKey): Promise<StoredDraft | null> => transaction(storageKey(key), current => ({
      write: false, next: null, result: current === null || tombstone(current) ? null : parseDraft(current),
    })),
    writeDraft: (key: DraftKey, expectedLocalRevision: number, draft: StoredDraft): Promise<number> => transaction(storageKey(key), current => {
      const revision = entryRevision(current);
      const recreated = tombstone(current);
      if (recreated ? expectedLocalRevision !== 0 && expectedLocalRevision !== revision : revision !== expectedLocalRevision)
        throw new Error("draft_conflict");
      const next = { ...parseDraft(draft, true), localRevision: revision + 1 };
      if (!Number.isSafeInteger(next.localRevision)) throw new Error("draft_corrupt");
      return { write: true, next, result: next.localRevision };
    }),
    deleteDraft: (key: DraftKey, expectedLocalRevision: number): Promise<void> => transaction(storageKey(key), current => {
      const revision = entryRevision(current);
      if (current === null) {
        if (expectedLocalRevision !== 0) throw new Error("draft_conflict");
        return { write: false, next: null, result: undefined };
      }
      if (tombstone(current)) {
        if (expectedLocalRevision !== 0 && expectedLocalRevision !== revision) throw new Error("draft_conflict");
        return { write: false, next: null, result: undefined };
      }
      if (revision !== expectedLocalRevision) throw new Error("draft_conflict");
      const next: Tombstone = { schemaVersion: 1, localRevision: revision + 1, deleted: true };
      return { write: true, next, result: undefined };
    }),
    listDrafts: async (identity: Identity): Promise<{ packageId: number; draft: StoredDraft }[]> => {
      const prefix = scope(identity), result = [];
      for (const [key, value] of await entries(prefix)) {
        if (!key.startsWith(prefix) || tombstone(value)) continue;
        const parsed: unknown = JSON.parse(key);
        if (!Array.isArray(parsed) || parsed.length !== 3 || !positive(parsed[2])) throw new Error("draft_corrupt");
        result.push({ packageId: Number(parsed[2]), draft: parseDraft(value) });
      }
      return result.sort((a, b) => b.packageId - a.packageId);
    },
  };
}

let database: Promise<IDBDatabase> | null = null;
function openDatabase(): Promise<IDBDatabase> {
  if (!globalThis.indexedDB) return Promise.reject(new Error("draft_storage_unavailable"));
  if (!database) database = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("dojo-package-drafts", 1);
    let failed = false;
    request.onupgradeneeded = () => request.result.createObjectStore("drafts");
    request.onerror = request.onblocked = () => {
      failed = true; database = null; reject(new Error("draft_storage_unavailable"));
    };
    request.onsuccess = () => {
      if (failed) { request.result.close(); return; }
      request.result.onversionchange = () => { request.result.close(); database = null; };
      resolve(request.result);
    };
  });
  return database;
}

const indexedTransaction: DraftTransaction = async (key, operation) => {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("drafts", "readwrite"), store = transaction.objectStore("drafts");
    const request = store.get(key);
    let result: ReturnType<typeof operation>["result"], failure: unknown;
    request.onsuccess = () => {
      try {
        const outcome = operation(request.result ?? null); result = outcome.result;
        if (outcome.write) { if (outcome.next === null) store.delete(key); else store.put(outcome.next, key); }
      } catch (error) { failure = error; transaction.abort(); }
    };
    transaction.oncomplete = () => resolve(result);
    transaction.onabort = () => reject(failure ?? transaction.error ?? new Error("draft_storage_unavailable"));
    transaction.onerror = () => { failure ??= transaction.error; };
  });
};

async function indexedEntries(prefix: string, remove = false): Promise<[string, unknown][]> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const result: [string, unknown][] = [];
    const transaction = db.transaction("drafts", remove ? "readwrite" : "readonly");
    const request = transaction.objectStore("drafts").openCursor(IDBKeyRange.bound(prefix, prefix + "\uffff"));
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;
      result.push([String(cursor.key), cursor.value]);
      if (remove) cursor.delete();
      cursor.continue();
    };
    transaction.oncomplete = () => resolve(result);
    transaction.onabort = () => reject(transaction.error ?? new Error("draft_storage_unavailable"));
    transaction.onerror = () => {};
  });
}

const store = createDraftStore(indexedTransaction, indexedEntries);
export const readDraft = store.readDraft;
export const writeDraft = store.writeDraft;
export const deleteDraft = store.deleteDraft;
export const listDrafts = store.listDrafts;
export async function clearIdentityDrafts(identity: Identity): Promise<void> {
  await indexedEntries(scope(identity), true);
}
