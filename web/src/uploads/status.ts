import type { UploadOut } from "../api/openapi";
import { UploadFlowError } from "./types";

const statuses = new Set(["receiving", "conflict", "queued", "processing", "finalized", "failed", "aborted"]);
export function isUploadStatus(value: unknown, size: number, id?: string): value is UploadOut {
  if (!value || typeof value !== "object") return false;
  const status = value as Partial<UploadOut>;
  if (typeof status.upload_id !== "string" || !status.upload_id || (id !== undefined && id !== status.upload_id)
    || status.declared_size_bytes !== size || !Number.isSafeInteger(status.received_bytes)
    || status.received_bytes! < 0 || status.received_bytes! > size || !statuses.has(status.status!)
    || !Array.isArray(status.received_ranges) || (status.error_reason != null && typeof status.error_reason !== "string")
    || (status.conflicts !== undefined && !Array.isArray(status.conflicts))) return false;
  let end = 0;
  let received = 0;
  for (const range of status.received_ranges) {
    if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isSafeInteger)
      || range[0] < end || range[1] <= range[0] || range[1] > size) return false;
    received += range[1] - range[0];
    end = range[1];
  }
  return received === status.received_bytes;
}

export function assertUploadStatus(value: unknown, size: number, id?: string): asserts value is UploadOut {
  if (!isUploadStatus(value, size, id)) throw new UploadFlowError("invalid-response");
}
