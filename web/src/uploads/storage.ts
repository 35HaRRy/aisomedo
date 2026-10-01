import { CHUNK_BYTES, type SavedUpload } from "./types";
import { isUploadStatus } from "./status";

const key = (clientId: number) => `aisomedo.uploads.v1:${clientId}`;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

function valid(value: unknown): value is SavedUpload {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<SavedUpload>;
  return typeof row.id === "string" && !!row.id && typeof row.filename === "string" && !!row.filename
    && typeof row.contentType === "string" && Number.isSafeInteger(row.size) && row.size! > 0
    && typeof row.lastModified === "number" && Number.isFinite(row.lastModified)
    && !!row.identity && row.identity.chunkBytes === CHUNK_BYTES && digest(row.identity.fingerprint)
    && Array.isArray(row.identity.chunkHashes) && row.identity.chunkHashes.length === Math.ceil(row.size! / CHUNK_BYTES)
    && row.identity.chunkHashes.every(digest) && (row.status === null || isUploadStatus(row.status, row.size!))
    && (row.skipped === undefined || typeof row.skipped === "boolean")
    && (row.pendingDecision === undefined || ["keep_both", "keep_selected", "keep_target"].includes(row.pendingDecision));
}

function metadata(row: SavedUpload): SavedUpload {
  const status = row.status;
  return { id: row.id, filename: row.filename, size: row.size, contentType: row.contentType, lastModified: row.lastModified,
    identity: { chunkBytes: row.identity.chunkBytes, chunkHashes: [...row.identity.chunkHashes], fingerprint: row.identity.fingerprint },
    ...(row.skipped ? { skipped: true } : {}),
    ...(row.pendingDecision ? { pendingDecision: row.pendingDecision } : {}),
    status: status ? { upload_id: status.upload_id, declared_size_bytes: status.declared_size_bytes,
      received_bytes: status.received_bytes, received_ranges: status.received_ranges.map(range => [...range]),
      status: status.status, error_reason: status.error_reason ?? null, conflicts: [] } : null };
}

export function readUploads(storage: Pick<Storage, "getItem">, clientId: number): { records: SavedUpload[]; available: boolean } {
  let raw: string | null;
  try { raw = storage.getItem(key(clientId)); }
  catch { return { available: false, records: [] }; }
  try {
    const envelope = raw ? JSON.parse(raw) : null;
    if (!envelope || envelope.version !== 1 || !Array.isArray(envelope.records)) return { available: true, records: [] };
    const ids = new Set<string>();
    const uploads = new Set<string>();
    const records: SavedUpload[] = [];
    for (const value of envelope.records) {
      if (!valid(value) || ids.has(value.id) || (value.status && uploads.has(value.status.upload_id))) continue;
      ids.add(value.id);
      if (value.status) uploads.add(value.status.upload_id);
      records.push(metadata(value));
    }
    return { available: true, records };
  } catch { return { available: true, records: [] }; }
}

export function writeUploads(storage: Pick<Storage, "setItem">, clientId: number, records: SavedUpload[]): boolean {
  try { storage.setItem(key(clientId), JSON.stringify({ version: 1, records: records.filter(valid).map(metadata) })); return true; }
  catch { return false; }
}
