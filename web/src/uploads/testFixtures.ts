import { createHash } from "node:crypto";
import { vi } from "vitest";
import type { UploadInitIn, UploadOut } from "../api/openapi";

export function installCrypto() {
  const digest = vi.fn(async (_algorithm: string, input: ArrayBuffer | Uint8Array) =>
    Uint8Array.from(createHash("sha256").update(input instanceof Uint8Array ? input : new Uint8Array(input)).digest()).buffer);
  vi.stubGlobal("crypto", { subtle: { digest }, randomUUID: () => Math.random().toString(36).slice(2) });
  return digest;
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
export function uploadServer({ conflicts = false } = {}) {
  const records = new Map<string, UploadOut>();
  const filenames = new Map<string, string>();
  let sequence = 0;
  const transport = {
    limits: vi.fn(async (_signal: AbortSignal) => ({ max_file_bytes: 2 ** 31, max_package_bytes: 20 * 2 ** 30 })),
    start: vi.fn(async (body: UploadInitIn, _signal: AbortSignal) => {
      const value: UploadOut = { upload_id: `upload-${++sequence}`, declared_size_bytes: body.declared_size_bytes,
        received_bytes: 0, received_ranges: [], status: conflicts ? "conflict" : "receiving", error_reason: null,
        conflicts: conflicts ? [{ media_id: body.filename.toLowerCase(), filename: body.filename,
          content_type: body.content_type, size_bytes: 100, uploaded_at: "2026-10-01T07:00:00Z",
          processed: { content_type: body.content_type.startsWith("video/") ? "video/mp4" : "image/jpeg" } }] : [] };
      filenames.set(value.upload_id, body.filename.toLowerCase());
      records.set(value.upload_id, value); return value;
    }),
    status: vi.fn(async (id: string, _signal: AbortSignal) => records.get(id)!),
    range: vi.fn(async (id: string, offset: number, _checksum: string, blob: Blob, _signal: AbortSignal) => {
      const previous = records.get(id)!;
      const received = Math.max(previous.received_bytes, offset + blob.size);
      const value = { ...previous, received_bytes: received, received_ranges: [[0, received]] };
      records.set(id, value); return value;
    }),
    complete: vi.fn(async (id: string, _signal: AbortSignal) => {
      const value = { ...records.get(id)!, status: "queued" };
      records.set(id, value); return value;
    }),
    resolve: vi.fn(async (id: string, body: { decision: string; apply_to_all?: boolean; target_media_id?: string | null; confirmed_overwrite?: boolean }, _signal: AbortSignal) => {
      let last = records.get(id)!;
      for (const [key, value] of records) {
        if (key !== id && (!body.apply_to_all || filenames.get(key) !== filenames.get(id))) continue;
        if (value.status !== "conflict") continue;
        last = { ...value, status: body.decision === "keep_target" ? "aborted" : "receiving", conflicts: [] };
        records.set(key, last);
      }
      return last;
    }),
  };
  return { transport, records };
}
