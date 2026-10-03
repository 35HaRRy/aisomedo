import { ApiError } from "../api/client";
import type { UploadLimitsOut, UploadOut } from "../api/openapi";
import { checkAbort, fingerprintFile } from "./identity";
import { assertUploadStatus } from "./status";
import { readUploads, writeUploads } from "./storage";
import { transferUpload } from "./transfer";
import { UploadFlowError, type ConflictResolution, type SavedUpload, type UploadRow, type UploadTransport, type UploadPhase } from "./types";

export interface UploadSnapshot {
  rows: readonly UploadRow[];
  limits: UploadLimitsOut | null;
  limitsError: boolean;
  storageAvailable: boolean;
  resolvingId?: string | null;
}
export interface UploadController {
  getSnapshot(): UploadSnapshot;
  subscribe(listener: () => void): () => void;
  initialize(signal: AbortSignal): Promise<void>;
  add(files: readonly File[]): Promise<void>;
  pause(id: string): void;
  pauseAll(): void;
  reset(): void;
  resume(id: string, file?: File): Promise<void>;
  retry(id: string, file?: File): Promise<void>;
  resolve(id: string, body: ConflictResolution): Promise<void>;
  dismiss(id: string): void;
  refresh(signal: AbortSignal): Promise<void>;
  dispose(): void;
}
interface Options {
  clientId: number;
  transport: UploadTransport;
  storage: Storage | null;
  onUnauthorized(): void;
  onPackageChanged(): void;
}
interface Entry { row: UploadRow; file?: File; verified: boolean; flight?: AbortController }

function conflictTargetIds(row: UploadRow): Set<string> {
  return new Set(row.status?.conflicts?.map(target => target?.media_id)
    .filter((value): value is string => typeof value === "string" && !!value));
}

// Release scheduler on cancellation even if a transport or digest settles late.
function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const cancel = () => reject(new DOMException("", "AbortError"));
    if (signal.aborted) cancel();
    else signal.addEventListener("abort", cancel, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", cancel));
  });
}

export function createUploadController(options: Options): UploadController {
  const { clientId, transport, storage, onUnauthorized, onPackageChanged } = options;
  const entries = new Map<string, Entry>();
  const pending = new Set<string>();
  const listeners = new Set<() => void>();
  const lifetime = new AbortController();
  let initialized = false;
  let sequence = 0;
  let queueGeneration = 0;
  let pumpFlight: Promise<void> | null = null;
  let refreshFlight: Promise<void> | null = null;
  let initializeFlight: Promise<void> | null = null;
  let snapshot: UploadSnapshot = { rows: [], limits: null, limitsError: false, storageAvailable: !!storage };
  const alive = () => !lifetime.signal.aborted;
  const valid = (entry: Entry, flight: AbortController) => alive() && entries.get(entry.row.id) === entry && entry.flight === flight && !flight.signal.aborted;

  function emit(persist = true) {
    if (persist && storage && alive()) {
      const records = Array.from(entries.values(), entry => entry.row).filter((row): row is UploadRow & SavedUpload => !!row.identity);
      if (!writeUploads(storage, clientId, records)) snapshot = { ...snapshot, storageAvailable: false };
    }
    snapshot = { ...snapshot, rows: Array.from(entries.values(), entry => structuredClone(entry.row)) };
    listeners.forEach(listener => listener());
  }
  function dispose() {
    if (!alive()) return;
    lifetime.abort();
    entries.forEach(entry => entry.flight?.abort());
    pending.clear(); entries.clear();
    snapshot = { ...snapshot, limits: null, resolvingId: null };
    emit(false);
    listeners.clear();
  }
  function failure(error: unknown, entry?: Entry) {
    if (!alive()) return;
    if (error instanceof ApiError && error.status === 401) { dispose(); onUnauthorized(); return; }
    if (!entry) { snapshot = { ...snapshot, limits: null, limitsError: true }; emit(false); return; }
    if (error instanceof DOMException && error.name === "AbortError") return;
    const code = error instanceof UploadFlowError ? error.code
      : error instanceof ApiError ? error.status === 0 ? "network" : error.status === 413 ? "oversize"
      : error.status === 404 ? "expired" : error.status === 409 && error.detail?.includes("package limit") ? "capacity"
      : error.status === 400 && error.detail?.includes("checksum") ? "checksum" : "server" : "server";
    const retained = ["queued", "processing", "failed", "expired", "conflict", "finalized"].includes(entry.row.phase);
    entry.row = { ...entry.row, error: code, diagnostic: retained ? entry.row.diagnostic : null,
      phase: code === "expired" ? "expired" : code === "wrong-file" ? "needs-file" : retained ? entry.row.phase : "retryable" };
    emit();
  }
  function applyStatus(entry: Entry, value: UploadOut, receiving: UploadPhase) {
    assertUploadStatus(value, entry.row.size, entry.row.status?.upload_id);
    if (snapshot.limits && value.package_id != null) snapshot = { ...snapshot, limits: { ...snapshot.limits, active_package_id: value.package_id } };
    if (entry.row.pendingDecision) {
      entry.row = { ...entry.row, skipped: value.status === "aborted" && entry.row.pendingDecision === "keep_target",
        pendingDecision: undefined };
    }
    const wasFinalized = entry.row.status?.status === "finalized";
    const phase: UploadPhase = value.status === "receiving" ? receiving : value.status === "aborted" ? entry.row.skipped ? "skipped" : "expired" : value.status as UploadPhase;
    entry.row = { ...entry.row, status: structuredClone(value), phase, error: phase === "expired" ? "expired" : phase === "conflict" ? "conflict" : null,
      diagnostic: value.status === "failed" ? value.error_reason ?? null : null };
    if (value.status === "finalized") {
      pending.delete(entry.row.id);
      entries.delete(entry.row.id);
      entry.file = undefined;
    }
    emit();
    if (value.status === "finalized" && !wasFinalized) onPackageChanged();
  }
  function newFlight(entry: Entry, parent?: AbortSignal) {
    const flight = new AbortController();
    const cancel = () => flight.abort();
    lifetime.signal.addEventListener("abort", cancel, { once: true });
    parent?.addEventListener("abort", cancel, { once: true });
    if (!alive() || parent?.aborted) flight.abort();
    entry.flight = flight;
    return { flight, finish: () => {
      lifetime.signal.removeEventListener("abort", cancel);
      parent?.removeEventListener("abort", cancel);
      if (entry.flight === flight) entry.flight = undefined;
    } };
  }
  async function query(entry: Entry, signal: AbortSignal) {
    if (!entry.row.status || entry.row.phase === "finalized" || entry.flight || !alive()) return;
    const { flight, finish } = newFlight(entry, signal);
    try {
      const value = await abortable(transport.status(entry.row.status.upload_id, flight.signal), flight.signal);
      if (valid(entry, flight)) {
        applyStatus(entry, value, entry.file ? "paused" : "needs-file");
      }
    } catch (error) { if (valid(entry, flight)) failure(error, entry); }
    finally { finish(); }
  }
  function sizeCheck(file: File) {
    if (!file.size) throw new UploadFlowError("empty");
    if (!snapshot.limits || snapshot.limitsError) throw new UploadFlowError("network");
    if (file.size > snapshot.limits.max_file_bytes) throw new UploadFlowError("oversize");
  }
  async function run(entry: Entry) {
    const { flight, finish } = newFlight(entry);
    const signal = flight.signal;
    try {
      const file = entry.file!;
      if (!entry.row.status) sizeCheck(file);
      if (!entry.verified) {
        if (entry.row.identity && (file.name !== entry.row.filename || file.size !== entry.row.size)) throw new UploadFlowError("wrong-file");
        entry.row = { ...entry.row, phase: "preparing", error: null, preparedBytes: 0 }; emit(false);
        const identity = await abortable(fingerprintFile(file, signal, bytes => {
          if (valid(entry, flight)) { entry.row = { ...entry.row, preparedBytes: bytes }; emit(false); }
        }), signal);
        if (!valid(entry, flight)) return;
        if (entry.row.identity && identity.fingerprint !== entry.row.identity.fingerprint) {
          entry.file = undefined; throw new UploadFlowError("wrong-file");
        }
        entry.row = { ...entry.row, identity }; entry.verified = true; emit();
      }
      if (!entry.row.status) {
        const value = await abortable(transport.start({ filename: entry.row.filename, content_type: entry.row.contentType, declared_size_bytes: entry.row.size,
          ...(snapshot.limits?.active_package_id != null ? { expected_package_id: snapshot.limits.active_package_id } : {}) }, signal), signal);
        if (!valid(entry, flight)) return;
        applyStatus(entry, value, "uploading");
        onPackageChanged();
      }
      if (entry.row.status!.status !== "receiving") return;
      entry.row = { ...entry.row, phase: "uploading", error: null }; emit(false);
      await abortable(transferUpload(file, entry.row.identity!, entry.row.status!, transport, signal, status => {
        if (valid(entry, flight)) applyStatus(entry, status, "uploading");
      }), signal);
    } catch (error) { if (valid(entry, flight)) failure(error, entry); }
    finally { finish(); }
  }
  function pump(): Promise<void> {
    if (pumpFlight) return pumpFlight;
    pumpFlight = (async () => {
      while (alive() && pending.size) {
        const id = pending.values().next().value!; pending.delete(id);
        const entry = entries.get(id);
        if (entry?.file && entry.row.phase === "waiting") await run(entry);
      }
    })().finally(() => { pumpFlight = null; });
    return pumpFlight;
  }
  async function resume(id: string, file?: File) {
    const entry = entries.get(id);
    if (!alive() || !entry || entry.flight || pending.has(id)
      || !["paused", "needs-file", "retryable"].includes(entry.row.phase)) return;
    if (file) {
      entry.file = file; entry.verified = false;
      if (!entry.row.status && !entry.row.identity) entry.row = { ...entry.row, filename: file.name, size: file.size,
        contentType: file.type || "application/octet-stream", lastModified: file.lastModified };
    }
    if (!entry.file) { entry.row = { ...entry.row, phase: "needs-file" }; emit(false); return; }
    entry.row = { ...entry.row, phase: "waiting", error: null }; emit(false);
    pending.add(id); await pump();
  }
  const controller: UploadController = {
    getSnapshot: () => snapshot,
    subscribe: listener => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    async initialize(signal) {
      if (!alive() || initializeFlight) return initializeFlight ?? undefined;
      initializeFlight = (async () => {
        const restore = !initialized;
        if (restore) {
          initialized = true;
          const saved = storage ? readUploads(storage, clientId) : { records: [], available: false };
          snapshot = { ...snapshot, storageAvailable: saved.available };
          for (const record of saved.records) {
            const phase: UploadPhase = !record.status || record.status.status === "receiving" ? "needs-file"
              : record.status.status === "aborted" ? record.skipped ? "skipped" : "expired" : record.status.status as UploadPhase;
            entries.set(record.id, { verified: false, row: { ...record, phase, preparedBytes: 0, error: null,
              diagnostic: record.status?.status === "failed" ? record.status.error_reason ?? null : null } });
          }
          emit(saved.available);
        }
        const cancel = () => request.abort();
        const request = new AbortController();
        signal.addEventListener("abort", cancel, { once: true });
        lifetime.signal.addEventListener("abort", cancel, { once: true });
        if (signal.aborted || !alive()) request.abort();
        try {
          const limits = await abortable(transport.limits(request.signal), request.signal);
          checkAbort(request.signal);
          if (!Number.isSafeInteger(limits.max_file_bytes) || limits.max_file_bytes <= 0
            || !Number.isSafeInteger(limits.max_package_bytes) || limits.max_package_bytes <= 0) throw new UploadFlowError("invalid-response");
          snapshot = { ...snapshot, limits, limitsError: false }; emit(false);
          // Reconcile restored rows once. Later limit reloads must not change
          // another row's explicit scheduling intent during a fresh retry.
          if (restore) for (const entry of entries.values()) { checkAbort(request.signal); await query(entry, request.signal); }
        } catch (error) { if (!request.signal.aborted && alive()) failure(error); }
        finally {
          signal.removeEventListener("abort", cancel); lifetime.signal.removeEventListener("abort", cancel);
        }
      })().finally(() => { initializeFlight = null; });
      return initializeFlight;
    },
    async add(files) {
      if (!alive() || !snapshot.limits || snapshot.limitsError) return;
      for (const file of files) {
        const row: UploadRow = { id: globalThis.crypto?.randomUUID?.() ?? `row-${Date.now()}-${++sequence}`, filename: file.name, size: file.size, contentType: file.type || "application/octet-stream",
          lastModified: file.lastModified, identity: null, status: null, phase: "waiting", preparedBytes: 0, error: null, diagnostic: null };
        const entry: Entry = { row, file, verified: false }; entries.set(row.id, entry);
        try { sizeCheck(file); pending.add(row.id); } catch (error) { failure(error, entry); }
      }
      emit(false); await pump();
    },
    pause(id) {
      const entry = entries.get(id);
      if (!entry || !alive() || !["preparing", "waiting", "uploading"].includes(entry.row.phase)) return;
      entry.flight?.abort(); pending.delete(id);
      entry.row = { ...entry.row, phase: "paused" }; emit();
    },
    pauseAll() {
      queueGeneration++;
      snapshot = { ...snapshot, resolvingId: null };
      pending.clear();
      for (const entry of entries.values()) {
        entry.flight?.abort();
        if (["preparing", "waiting", "uploading"].includes(entry.row.phase)) entry.row = { ...entry.row, phase: "paused" };
      }
      emit();
    },
    reset() {
      controller.pauseAll();
      entries.clear();
      snapshot = { ...snapshot, resolvingId: null, limits: snapshot.limits ? { ...snapshot.limits, active_package_id: 0 } : null };
      emit();
    },
    resume,
    async resolve(id, body) {
      const generation = queueGeneration;
      const entry = entries.get(id);
      if (!alive() || !entry || snapshot.resolvingId || initializeFlight || entry.row.phase !== "conflict" || !entry.row.status) return;
      if (!["keep_both", "keep_selected", "keep_target"].includes(body.decision)
        || (body.decision === "keep_selected" && (!body.confirmed_overwrite || !body.target_media_id
          || !entry.row.status.conflicts?.some(target => target?.media_id === body.target_media_id)))) {
        failure(new UploadFlowError("invalid-response"), entry); return;
      }
      snapshot = { ...snapshot, resolvingId: id }; emit(false);
      if (body.apply_to_all) {
        // Storage deliberately strips target metadata. Recover all unknown
        // conflicts before deciding which uploads this server-side bulk affects.
        const conflicts = Array.from(entries.values()).filter(candidate => candidate.row.phase === "conflict");
        conflicts.forEach(candidate => { candidate.flight?.abort(); candidate.flight = undefined; });
        for (const candidate of conflicts) {
          if (!alive()) return;
          if (conflictTargetIds(candidate.row).size) continue;
          await query(candidate, lifetime.signal);
          if (!alive()) return;
          if (candidate.row.phase === "conflict" && !conflictTargetIds(candidate.row).size) {
            failure(new UploadFlowError("network"), entry);
            snapshot = { ...snapshot, resolvingId: null }; emit(false); return;
          }
        }
        if (entry.row.phase !== "conflict") {
          snapshot = { ...snapshot, resolvingId: null }; emit(false); return;
        }
      }
      // Server collision targets encode Unicode casefold compatibility. Sharing a
      // target is safer than JavaScript lowercasing (which is not Python casefold).
      const targetIds = conflictTargetIds(entry.row);
      const candidates = body.apply_to_all ? Array.from(entries.values()).filter(candidate => candidate === entry
        || (candidate.row.phase === "conflict" && Array.from(conflictTargetIds(candidate.row)).some(target => targetIds.has(target)))) : [entry];
      for (const candidate of candidates) {
        candidate.flight?.abort(); candidate.flight = undefined;
        candidate.row = { ...candidate.row, pendingDecision: body.decision };
      }
      emit();
      const { flight, finish } = newFlight(entry);
      let resolutionError: UploadRow["error"] = null;
      try {
        // Bulk response can belong to another upload. Always reconcile by ID.
        await abortable(transport.resolve(entry.row.status.upload_id, body, flight.signal), flight.signal);
      } catch (error) {
        if (valid(entry, flight)) {
          // A definitive rejection must not later turn an unrelated abort into a skip.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500)
            candidates.forEach(candidate => { candidate.row = { ...candidate.row, pendingDecision: undefined }; });
          failure(error, entry); resolutionError = entry.row.error;
        }
      } finally { finish(); }
      if (generation !== queueGeneration) return;
      try {
        for (const candidate of candidates) {
          if (!alive() || generation !== queueGeneration) return;
          await query(candidate, lifetime.signal);
          if (candidate.row.phase === "paused" && candidate.file && !candidate.row.error) {
            candidate.row = { ...candidate.row, phase: "waiting" }; pending.add(candidate.row.id); emit();
          }
        }
        if (alive() && entry.row.phase === "conflict" && resolutionError) {
          entry.row = { ...entry.row, error: resolutionError }; emit();
        }
        if (alive()) onPackageChanged();
      } finally {
        if (alive()) { snapshot = { ...snapshot, resolvingId: null }; emit(false); }
      }
      await pump();
    },
    async retry(id, file) {
      const entry = entries.get(id);
      if (!alive() || !entry || entry.flight || pending.has(id) || ["conflict", "finalized", "skipped"].includes(entry.row.phase)) return;
      if (["queued", "processing"].includes(entry.row.phase)) { await query(entry, lifetime.signal); return; }
      const fresh = ["failed", "expired"].includes(entry.row.phase) || !entry.row.status
        || entry.row.status.status === "failed" || entry.row.status.status === "aborted";
      if (fresh) {
        await controller.initialize(lifetime.signal);
        if (!alive() || !snapshot.limits || snapshot.limitsError) return;
        const selected = file ?? entry.file;
        if (!selected) {
          entry.row = { ...entry.row, status: null, identity: null, diagnostic: null, error: null, phase: "needs-file" };
          emit(); return;
        }
        entry.file = selected; entry.verified = false;
        entry.row = { ...entry.row, filename: selected.name, size: selected.size, contentType: selected.type || "application/octet-stream",
          lastModified: selected.lastModified, status: null, identity: null, diagnostic: null, phase: "retryable" };
      }
      await resume(id, file);
    },
    dismiss(id) {
      const entry = entries.get(id);
      if (alive() && entry && !snapshot.resolvingId && ["finalized", "failed", "expired", "conflict", "skipped"].includes(entry.row.phase)) { entries.delete(id); emit(); }
    },
    async refresh(signal) {
      if (!alive() || refreshFlight || initializeFlight || snapshot.resolvingId) return refreshFlight ?? undefined;
      refreshFlight = (async () => {
        for (const entry of entries.values()) {
          if (!alive() || signal.aborted || snapshot.resolvingId) break;
          if (["queued", "processing", "conflict"].includes(entry.row.phase)) await query(entry, signal);
        }
      })().finally(() => { refreshFlight = null; });
      return refreshFlight;
    },
    dispose,
  };
  return controller;
}
